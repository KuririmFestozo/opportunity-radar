"""Conservative availability verification for non-Gupy job boards.

A reachable job description is NOT proof that applications are open.
HTTP errors, empty JavaScript shells, home-page redirects and login-gated
applications are 'unverified'. Only explicit closure or an expired,
unambiguous application deadline is 'closed'.

The SQLite verification overlay is keyed by source + native posting ID,
allowing the web UI to separate unverified from unchecked opportunities.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from functools import lru_cache
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

# Every source family that can appear in the current collector registry.
# Disabled collectors are retained for historical postings.
SUPPORTED = frozenset({
    "gupy_global", "gupy_api", "gupy_public", "99jobs", "vagas_com",
    "ciee", "cargill", "ashby", "lever", "greenhouse", "workday",
    "smartrecruiters", "inhire", "izirh", "eightfold", "teamtailor",
    "totvs", "successfactors", "walljobs", "cia_estagios", "nube",
    "iel", "superestagios", "taqe", "bettha", "matchbox", "cia_talentos",
})
_EXACT = {
    "99jobs": {"99jobs.com", "www.99jobs.com"},
    "vagas_com": {"vagas.com.br", "www.vagas.com.br"},
    "ciee": {"portal.ciee.org.br"},
    "cargill": {"careers.cargill.com"},
    "totvs": {"atracaodetalentos.totvs.app"},
    "walljobs": {"app.walljobs.com.br"},
    "cia_estagios": {"ciadeestagios.com.br", "www.ciadeestagios.com.br"},
    "nube": {"nube.com.br", "www.nube.com.br"},
    "iel": {"carreiras.iel.org.br"},
    "superestagios": {"superestagios.com.br", "www.superestagios.com.br"},
    "taqe": {"vagas.taqe.com.br"},
    "bettha": {"admin-vagas.bettha.com", "www.bettha.com", "bettha.com"},
    "matchbox": {"matchboxbrasil.com", "www.matchboxbrasil.com"},
    "cia_talentos": {"ciadetalentos.com.br", "www.ciadetalentos.com.br"},
    "smartrecruiters": {"jobs.smartrecruiters.com"},
    "lever": {"jobs.lever.co"},
    "greenhouse": {"boards.greenhouse.io", "job-boards.greenhouse.io"},
    "ashby": {"jobs.ashbyhq.com"},
}
_SUFFIXES = {
    "gupy_global": ("gupy.io",),
    "gupy_public": ("gupy.io",),
    "gupy_api": ("gupy.io",),
    "workday": ("myworkdayjobs.com",),
    "inhire": ("inhire.app",),
    "izirh": ("izirh.io",),
    "eightfold": ("eightfold.ai",),
    "teamtailor": ("teamtailor.com",),
    "greenhouse": ("greenhouse.io",),
    "ashby": ("ashbyhq.com",),
}


@lru_cache(maxsize=1)
def _configured_hosts() -> dict[str, set[str]]:
    """Configured corporate domains, not arbitrary addresses from a DB."""
    from config.successfactors import SUCCESSFACTORS_PORTALS
    from config.eightfold import EIGHTFOLD_TENANTS
    from config.additional_ats import TEAMTAILOR_BOARDS

    result = {"successfactors": set(), "eightfold": set(),
              "teamtailor": set()}
    for entry in SUCCESSFACTORS_PORTALS:
        urls = ([entry.get("career_url")] +
                list(entry.get("listing_urls") or []))
        for url in urls:
            host = urlsplit(str(url or "")).hostname
            if host:
                result["successfactors"].add(host.lower())
    for source, collection in (("eightfold", EIGHTFOLD_TENANTS),
                               ("teamtailor", TEAMTAILOR_BOARDS)):
        for item in collection:
            host = urlsplit(str(item.get("career_url") or "")).hostname
            if host:
                result[source].add(host.lower())
    return result


def source_families() -> tuple[str, ...]:
    """All possible source values currently emitted by collector modules."""
    return tuple(sorted(SUPPORTED))


def source_coverage(conn: sqlite3.Connection) -> list[dict]:
    """Per-source counts, without creating tables or touching the DB."""
    has_checks = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='source_availability_checks'"
    ).fetchone() is not None
    join = ("""LEFT JOIN source_availability_checks c
        ON c.source=p.source AND c.source_job_id=p.source_job_id"""
        if has_checks else "")
    verdict = "c.verdict" if has_checks else "NULL"
    rows = conn.execute(f"""
        SELECT p.source, COUNT(*) historical,
            SUM(CASE WHEN p.is_active=1 THEN 1 ELSE 0 END) active,
            SUM(CASE WHEN {verdict}='open' THEN 1 ELSE 0 END) verified_open,
            SUM(CASE WHEN {verdict}='closed' THEN 1 ELSE 0 END) verified_closed,
            SUM(CASE WHEN {verdict}='unverified' THEN 1 ELSE 0 END) unverified,
            SUM(CASE WHEN {verdict} IS NULL THEN 1 ELSE 0 END) unchecked
        FROM source_postings p {join}
        GROUP BY p.source ORDER BY p.source
    """).fetchall()
    return [dict(zip(("source", "historical", "active", "verified_open",
                      "verified_closed", "unverified", "unchecked"), row))
            for row in rows]


CLOSED = {"inscricoes encerradas", "candidaturas encerradas",
          "esta vaga foi encerrada", "vaga encerrada", "applications closed",
          "esta oportunidade foi encerrada"}
OPEN = {"inscricoes abertas", "applications open", "applications are open"}
_DEADLINE = re.compile(
    r"\binscri(?:cao|coes)\b.{0,100}?\b(?:ate|ate o dia)\s*"
    r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", re.IGNORECASE
)


def plain(raw: str) -> str:
    result = unicodedata.normalize("NFKD", str(raw).casefold())
    return " ".join("".join(c for c in result if not unicodedata.combining(c)).split())


def safe_url(source: str, raw: str) -> str | None:
    """Fetch only HTTPS vacancies from provider-owned or configured hosts.

    This is a defense-in-depth host allowlist. 3xx redirects are *never*
    followed, so even an owned site redirecting to another host is not fetched.
    """
    try:
        if source not in SUPPORTED:
            return None
        parts = urlsplit(str(raw or ""))
        host = (parts.hostname or "").lower().rstrip(".")
        if (parts.scheme != "https" or not host or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or any(ch in host for ch in (":", "%", ".."))):
            return None
        exact = host in _EXACT.get(source, set())
        vendor = any(host == suffix or host.endswith("." + suffix)
                     for suffix in _SUFFIXES.get(source, ()))
        configured = host in _configured_hosts().get(source, set())
        if not (exact or vendor or configured):
            return None

        path = parts.path or "/"
        # Generic careers home pages, listing and search pages are not job
        # application pages; never infer the state of a specific posting there.
        if path in {"/", "/jobs", "/vagas", "/search", "/careers"}:
            return None
        if source == "cargill" and "/job/" not in path:
            return None
        if source == "bettha" and not path.startswith("/hotsite/"):
            return None
        if source == "iel" and "/vaga/" not in path:
            return None
        if source == "cia_estagios" and not path.startswith("/vagas/"):
            return None
        if source == "99jobs" and not re.search(r"/(?:jobs|vagas)/\d+", path):
            return None
        # SuccessFactors may have a query-encoded unique job. Keep only those
        # known identifier fields and strip tracking parameters.
        safe_queries = ("job", "jobId", "jobid", "reqId", "reqid", "jobID")
        from urllib.parse import parse_qsl, urlencode, urlunsplit
        kept = [(key, val) for key, val in parse_qsl(parts.query)
                if key in safe_queries and 0 < len(val) <= 120]
        return urlunsplit(("https", host, path, urlencode(kept), ""))
    except (ValueError, TypeError):
        return None


def normalize_url(raw: str) -> str:
    """Match a supplied URL to the catalog, ignoring only tracking params."""
    try:
        p = urlsplit(str(raw or ""))
        host = (p.hostname or "").lower().removeprefix("www.")
        return f"{host}{p.path.rstrip('/').casefold()}"
    except (TypeError, ValueError):
        return ""


def classify_html(source: str, html: str, *, today: date | None = None):
    today = today or date.today()
    soup = BeautifulSoup(html[:1_500_000], "html.parser")
    for node in soup(["script", "style", "noscript", "template"]):
        node.decompose()
    text = plain(soup.get_text(" ", strip=True))
    for node in soup.select("h1,h2,h3,h4,p,div,span,[role='alert']"):
        if len(node.get_text(" ", strip=True)) > 150:
            continue
        phrase = plain(node.get_text(" ", strip=True)).strip(" .!:")
        if phrase in CLOSED:
            return "closed", "explicit_closed_message"

    # Never infer the year from a program title (e.g. "2027"). Only a
    # full, published application deadline can establish expiration.
    if source == "cia_estagios":
        match = _DEADLINE.search(text)
        if match:
            day, month, explicit_year = match.groups()
            if explicit_year:
                try:
                    deadline = date(int(explicit_year), int(month), int(day))
                    if deadline < today:
                        return "closed", f"deadline_{deadline.isoformat()}"
                except ValueError:
                    pass

    if source == "iel" and (
        "faca login e se candidate" in text
        or "fazer login e se candidate" in text
        or "fazer login e se candidatar" in text
        or "acesso candidato" in text
    ):
        return "unverified", "application_requires_login"

    for node in soup.select("h1,h2,h3,h4,p,[role='alert']"):
        phrase = plain(node.get_text(" ", strip=True)).strip(" .!:")
        if phrase in OPEN:
            return "open", "explicit_applications_open"

    if len(text) < 35:
        return "unverified", "no_readable_job_content"

    # The visible description or a clickable 'Inscreva-se' alone is insufficient.
    return "unverified", "no_confirmed_application_state"


def probe(source: str, raw_url: str, *, today: date | None = None):
    url = safe_url(source, raw_url)
    if url is None:
        return "unverified", "unsupported_or_unsafe_url"
    try:
        response = requests.get(
            url, timeout=(5, 12), allow_redirects=False,
            headers={"User-Agent": "OpportunityRadar/1.0",
                     "Accept": "text/html"},
        )
        if 300 <= response.status_code < 400:
            return "unverified", "redirect_from_job"
        if response.status_code != 200:
            return "unverified", f"http_{response.status_code}"
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            return "unverified", "not_html"
        return classify_html(source, response.text, today=today)
    except requests.RequestException as error:
        return "unverified", f"network_{type(error).__name__}"


def ensure_schema(conn: sqlite3.Connection):
    conn.execute("""
      CREATE TABLE IF NOT EXISTS source_availability_checks (
        source TEXT NOT NULL,
        source_job_id TEXT NOT NULL,
        verdict TEXT NOT NULL CHECK(verdict IN ('open','closed','unverified')),
        evidence TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        PRIMARY KEY(source,source_job_id)
      )
    """)
    conn.execute("""
      CREATE INDEX IF NOT EXISTS idx_source_availability_verdict
      ON source_availability_checks(verdict,checked_at)
    """)


def select_postings(conn: sqlite3.Connection, *, urls=None, limit=150):
    """Audit EVERY registered family, distributing checks fairly.

    Unknown historical source keys remain visible in source_coverage;
    unregistered/unsafe URLs are never fetched.
    """
    if urls:
        wanted = {normalize_url(url) for url in urls}
        if not wanted or not all(wanted):
            raise ValueError("URL de consulta invalida")
        matches = []
        for source, job_id, url in conn.execute("""
            SELECT source, source_job_id, url FROM source_postings
        """):
            if normalize_url(url) in wanted:
                matches.append((source, job_id, url))
        unmatched = sorted(wanted - {
            normalize_url(row[2]) for row in matches
        })
        return matches, unmatched
    if limit <= 0:
        return [], []

    has_checks = conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='source_availability_checks'"
    ).fetchone() is not None
    join = ("""LEFT JOIN source_availability_checks c
        ON c.source=p.source AND c.source_job_id=p.source_job_id"""
        if has_checks else "")
    checked = "COALESCE(c.checked_at,'')" if has_checks else "''"
    sources = [
        str(row[0]) for row in conn.execute(
            "SELECT DISTINCT source FROM source_postings "
            "WHERE is_active=1 ORDER BY source"
        )
    ]
    queues = {}
    for source in sources:
        if source not in SUPPORTED:
            continue
        queues[source] = conn.execute(
            f"""SELECT p.source,p.source_job_id,p.url
            FROM source_postings p {join}
            WHERE p.is_active=1 AND p.source=?
            ORDER BY {checked} ASC, p.last_seen_at ASC
            LIMIT ?""",
            (source, limit),
        ).fetchall()
    # Round robin across providers: no single dominant ATS consumes the batch.
    result = []
    for index in range(limit):
        progress = False
        for source in sorted(queues):
            if index < len(queues[source]):
                result.append(tuple(queues[source][index]))
                progress = True
                if len(result) >= limit:
                    return result, []
        if not progress:
            break
    return result, []


def apply_result(conn, source, job_id, verdict, evidence, *, checked_at=None):
    ensure_schema(conn)
    now = checked_at or datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT verdict FROM source_availability_checks "
        "WHERE source=? AND source_job_id=?", (source, job_id)
    ).fetchone()
    # Never turn a confirmed-closed posting back into an unchecked or
    # ambiguous state due to an HTTP failure, redirect or login wall.
    if existing is not None and existing[0] == "closed" and verdict != "closed":
        return 0
    conn.execute("""
      INSERT INTO source_availability_checks
            (source,source_job_id,verdict,evidence,checked_at)
      VALUES (?,?,?,?,?)
      ON CONFLICT(source,source_job_id) DO UPDATE SET
            verdict=excluded.verdict,
            evidence=excluded.evidence,
            checked_at=excluded.checked_at
    """, (source, job_id, verdict, evidence, now))
    if verdict != "closed":
        return 0
    updated = conn.execute("""
      UPDATE source_postings SET is_active=0,
          inactive_at=COALESCE(inactive_at,?),
          last_checked_at=?
      WHERE source=? AND source_job_id=? AND is_active=1
    """, (now, now, source, job_id)).rowcount
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
        conn.execute("""
          UPDATE jobs SET is_active=0, inactive_at=COALESCE(inactive_at,?),
              last_checked_at=?
          WHERE source=? AND source_job_id=?
        """, (now, now, source, job_id))
    return updated



def closed_posting_keys(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='source_availability_checks'"
    ).fetchone()
    if not exists:
        return set()
    return {
        (str(source), str(job_id))
        for source, job_id in conn.execute(
            "SELECT source,source_job_id FROM source_availability_checks "
            "WHERE verdict='closed'"
        )
    }


def suppress_confirmed_closed(jobs, closed):
    kept = [job for job in jobs if
            (job.source, str(job.source_job_id)) not in closed]
    return kept, len(jobs) - len(kept)



def audit_sources(conn: sqlite3.Connection, *, limit=100, workers=6,
                  apply=True, urls=None):
    """Bounded, fair audit across all collectors, with source-level reporting.

    Network requests run concurrently but SQLite changes occur on the calling
    thread. Unknown/redirect/login states never close an opportunity.
    """
    if not 0 <= limit <= 2000 or not 1 <= workers <= 12:
        raise ValueError("limit must be 0..2000 and workers 1..12")
    candidates, unmatched = select_postings(conn, urls=urls, limit=limit)
    counts = Counter()
    by_source = {}
    for x in unmatched:
        print(f"[NOT FOUND] {x}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(probe, source, url): (source, job_id, url)
            for source, job_id, url in candidates
        }
        for future in as_completed(futures):
            source, job_id, url = futures[future]
            try:
                verdict, evidence = future.result()
            except Exception:
                verdict, evidence = "unverified", "unexpected_check_error"
            counts[verdict] += 1
            by_source.setdefault(source, Counter())[verdict] += 1
            if apply:
                counts["inactivated"] += apply_result(
                    conn, source, job_id, verdict, evidence
                )
    if apply:
        conn.commit()
    return {
        "checked": len(candidates), "open": counts["open"],
        "closed": counts["closed"], "unverified": counts["unverified"],
        "inactivated": counts["inactivated"],
        "by_source": {k: dict(v) for k, v in sorted(by_source.items())},
        "unmatched": unmatched,
    }
