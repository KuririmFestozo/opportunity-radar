"""Audit Gupy postings by explicit closure evidence, never by search absence."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import base64
import binascii
import json
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

GUPY_SOURCES = ("gupy_global", "gupy_public", "gupy_api")
TERMINAL = {"closed", "canceled", "cancelled", "encerrada", "cancelada"}
BANNERS = {
    "esta vaga foi encerrada", "esta vaga esta encerrada",
    "esta vaga foi cancelada", "esta vaga esta cancelada",
    "vaga encerrada", "vaga cancelada",
    "inscricoes encerradas", "candidaturas encerradas",
    "inscricoes para esta vaga encerradas",
    "o periodo de inscricoes para esta vaga foi encerrado",
    "o prazo de inscricao para esta vaga foi encerrado",
    "nao e mais possivel se candidatar a esta vaga",
    "essa vaga nao esta mais disponivel",
    "esta vaga nao esta mais disponivel",
    "applications closed", "applications are closed",
    "this position has been paused by the company",
    "this job is no longer available",
    "this position is no longer available",
}
HEADERS = {"User-Agent": "OpportunityRadar/1.0", "Accept": "text/html"}


def explicitly_closed(job) -> bool:
    if job.source not in GUPY_SOURCES:
        return False
    metadata = job.metadata or {}
    return (str(metadata.get("gupy_status") or "").strip().lower() in TERMINAL
            or bool(metadata.get("gupy_closed_at")))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gupy_url_checks (
            source TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            verdict TEXT NOT NULL CHECK(verdict IN ('closed','unknown')),
            evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (source, source_job_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gupy_url_checks_checked "
                 "ON gupy_url_checks(checked_at)")


def closed_keys(conn) -> set[tuple[str, str]]:
    ensure_schema(conn)
    return {
        (str(row[0]), str(row[1])) for row in conn.execute(
            "SELECT source, source_job_id FROM gupy_url_checks WHERE verdict='closed'"
        )
    }


def filter_discoveries(jobs, permanently_closed):
    kept, explicit, repeated = [], set(), 0
    for job in jobs:
        key = (job.source, str(job.source_job_id))
        if explicitly_closed(job):
            explicit.add(key)
        elif key in permanently_closed:
            repeated += 1
        else:
            kept.append(job)
    return kept, explicit, {"explicit": len(explicit), "previously_closed": repeated}


def mark_closed(conn, keys, *, checked_at=None, evidence="source_terminal_status"):
    ensure_schema(conn)
    now = checked_at or datetime.now(timezone.utc).isoformat()
    changed = 0
    for source, job_id in keys:
        if source not in GUPY_SOURCES:
            continue
        row = conn.execute(
            "SELECT is_active FROM jobs WHERE source=? AND source_job_id=?",
            (source, job_id),
        ).fetchone()
        if row is None:
            continue
        changed += int(bool(row[0]))
        conn.execute("""
            UPDATE jobs SET is_active=0, last_checked_at=?,
                missing_since=COALESCE(missing_since, ?),
                inactive_at=COALESCE(inactive_at, ?),
                miss_count=MAX(miss_count,2)
            WHERE source=? AND source_job_id=?
        """, (now, now, now, source, job_id))
        conn.execute("""
            INSERT INTO gupy_url_checks(source,source_job_id,checked_at,verdict,evidence)
            VALUES(?,?,?,'closed',?)
            ON CONFLICT(source,source_job_id) DO UPDATE SET
                checked_at=excluded.checked_at,verdict='closed',
                evidence=excluded.evidence
        """, (source, job_id, now, evidence))
    return changed


def gupy_job_id(raw):
    """Get a Gupy numeric ID from old /jobs/123 and new /job/<Base64> links."""
    try:
        parts = urlsplit(str(raw or ""))
        host = (parts.hostname or "").lower()
        if (parts.scheme != "https" or not host.endswith(".gupy.io")
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443)):
            return None
        old = re.fullmatch(r"/jobs/([0-9]{1,16})/?", parts.path)
        if old:
            return old.group(1)
        new = re.fullmatch(r"/job/([A-Za-z0-9_-]{16,512}={0,2})/?", parts.path)
        if not new:
            return None
        token = new.group(1)
        payload = base64.b64decode(token + "=" * (-len(token) % 4),
                                   altchars=b"-_", validate=True)
        if len(payload) > 500:
            return None
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get("source") != "gupy_portal":
            return None
        job_id = data.get("jobId")
        if type(job_id) is int and 0 < job_id < 10**16:
            return str(job_id)
    except (ValueError, UnicodeDecodeError, TypeError, OverflowError,
            binascii.Error):
        return None
    return None


def safe_url(raw):
    """Only probe validated official Gupy job pages; discard arbitrary query."""
    try:
        parts = urlsplit(str(raw or ""))
        if gupy_job_id(raw) is None:
            return None
        return urlunsplit(("https", (parts.hostname or "").lower(),
                           parts.path, "", ""))
    except (ValueError, TypeError):
        return None


def _plain(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(x for x in value
                            if not unicodedata.combining(x)).split()).strip(" .!:")


def explicit_page_closure(html):
    soup = BeautifulSoup(html[:1_000_000], "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # Check only short visible alerts/headings/paragraphs, not full descriptions.
    for tag in soup.select("h1,h2,h3,h4,p,[role='alert'],[aria-live='assertive']"):
        text = _plain(tag.get_text(" ", strip=True))
        if len(text) <= 180 and text in BANNERS:
            return True
    # On newer Gupy pages "Applications closed" is a standalone text node
    # within a generic div/span, not necessarily an alert or heading.
    # Match exact short nodes only, never arbitrary description substrings.
    for node in soup.stripped_strings:
        text = _plain(str(node))
        if len(text) <= 140 and text in BANNERS:
            return True
    return False


def select_url_candidates(conn, links):
    """Find existing postings using supplied Gupy job URLs, not scan order.

    A supplied URL that is not present in this SQLite is reported as unmatched.
    We never create synthetic jobs or infer closure from URL absence.
    """
    wanted = {}
    for raw in links:
        numeric = gupy_job_id(raw)
        url = safe_url(raw)
        if numeric is None or url is None:
            raise ValueError(f"URL da Gupy nao reconhecida: {raw}")
        wanted.setdefault(numeric, url)
    if not wanted:
        return [], []

    entries = []
    matched = set()
    rows = conn.execute("""
        SELECT source, source_job_id, job_json
        FROM jobs
        WHERE is_active=1 AND source IN ('gupy_global','gupy_public','gupy_api')
    """).fetchall()
    for source, source_job_id, payload in rows:
        try:
            stored = json.loads(payload).get("url")
        except (ValueError, TypeError, AttributeError):
            stored = None
        source_id = str(source_job_id)
        stored_id = gupy_job_id(stored)
        job_id = stored_id or (source_id if source_id.isdecimal() else None)
        if job_id not in wanted:
            continue
        # For specific user-provided URLs, probe the exact confirmed
        # public vacancy page even when the stored portal URL is stale.
        entries.append((str(source), source_id, wanted[job_id]))
        matched.add(job_id)
    return entries, sorted(set(wanted) - matched)


def probe_url(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=(5, 12),
                                allow_redirects=False)
        if response.status_code != 200:
            return "unknown", f"http_{response.status_code}"
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            return "unknown", "non_html"
        if explicit_page_closure(response.text):
            return "closed", "explicit_closed_banner"
        return "unknown", "no_explicit_closed_banner"
    except requests.RequestException as exc:
        return "unknown", f"network_{type(exc).__name__}"


def select_candidates(conn, limit):
    if limit <= 0:
        return []
    ensure_schema(conn)
    rows = conn.execute("""
        SELECT j.source, j.source_job_id, j.job_json
        FROM jobs j LEFT JOIN gupy_url_checks a
          ON a.source=j.source AND a.source_job_id=j.source_job_id
        WHERE j.is_active=1 AND j.source IN ('gupy_global','gupy_public','gupy_api')
        ORDER BY COALESCE(a.checked_at,'') ASC, j.last_seen_at ASC,
                 j.source, j.source_job_id LIMIT ?
    """, (limit * 20,)).fetchall()
    chosen = []
    for source, job_id, payload in rows:
        try:
            url = safe_url(json.loads(payload).get("url"))
        except (ValueError, AttributeError, TypeError):
            url = None
        if url:
            chosen.append((str(source), str(job_id), url))
            if len(chosen) == limit:
                break
    return chosen


def audit_gupy(conn, *, limit=150, workers=6, apply=True, urls=None):
    if not 0 <= limit <= 2000 or not 1 <= workers <= 12:
        raise ValueError("limit 0-2000; workers 1-12")
    if urls:
        candidates, unmatched = select_url_candidates(conn, urls)
    else:
        candidates, unmatched = select_candidates(conn, limit), []
    stats = {"checked": 0, "closed": 0, "unknown": 0, "inactivated": 0}
    if unmatched:
        print("[GUPY] IDs nao encontrados neste banco ativo: "
              + ", ".join(unmatched))
    if not candidates:
        return stats
    now = datetime.now(timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_url, url): (source, job_id)
                   for source, job_id, url in candidates}
        for future in as_completed(futures):
            source, job_id = futures[future]
            try:
                verdict, evidence = future.result()
            except Exception:
                verdict, evidence = "unknown", "probe_error"
            stats["checked"] += 1
            stats[verdict] += 1
            if not apply:
                continue
            if verdict == "closed":
                stats["inactivated"] += mark_closed(
                    conn, {(source, job_id)}, checked_at=now, evidence=evidence
                )
            else:
                conn.execute("""
                    INSERT INTO gupy_url_checks(source,source_job_id,checked_at,verdict,evidence)
                    VALUES(?,?,?,'unknown',?)
                    ON CONFLICT(source,source_job_id) DO UPDATE SET
                        checked_at=excluded.checked_at,
                        verdict=CASE WHEN gupy_url_checks.verdict='closed'
                                     THEN 'closed' ELSE 'unknown' END,
                        evidence=excluded.evidence
                """, (source, job_id, now, evidence))
    if apply:
        conn.commit()
    return stats
