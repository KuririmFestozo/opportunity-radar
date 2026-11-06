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
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

SUPPORTED = {"99jobs", "bettha", "cargill", "cia_estagios", "iel"}
_ALLOWED = {
    "99jobs": ("99jobs.com",),
    "bettha": ("admin-vagas.bettha.com", "bettha.com"),
    "cargill": ("careers.cargill.com",),
    "cia_estagios": ("www.ciadeestagios.com.br",),
    "iel": ("carreiras.iel.org.br",),
}
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
    """Restrict network requests to exact expected provider hosts (no SSRF)."""
    try:
        parts = urlsplit(str(raw or ""))
        host = (parts.hostname or "").lower()
        allowed = _ALLOWED.get(source, ())
        if (parts.scheme != "https" or
            (host not in allowed and not (
                source == "99jobs" and host.endswith(".99jobs.com")
            )) or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443)):
            return None
        path = parts.path or "/"
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
        return f"https://{host}{path}"
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
    if len(text) < 70:
        return "unverified", "no_readable_job_content"

    for node in soup.select("h1,h2,h3,h4,p,div,span,[role='alert']"):
        if len(node.get_text(" ", strip=True)) > 150:
            continue
        phrase = plain(node.get_text(" ", strip=True)).strip(" .!:")
        if phrase in CLOSED:
            return "closed", "explicit_closed_message"

    # Specific published application deadlines can prove closure. A 2027
    # program with an unqualified 30/10 is treated as the 2026 cycle,
    # never inferred from current year for arbitrary undated vacancies.
    if source == "cia_estagios":
        match = _DEADLINE.search(text)
        if match:
            day, month, explicit_year = match.groups()
            heading = " ".join(plain(tag.get_text(" ", strip=True))
                               for tag in soup.select("h1,h2")[:3])
            cycle = re.search(r"\b(20\d{2})\b", heading)
            year = int(explicit_year) if explicit_year else (
                int(cycle.group(1)) - 1 if cycle else None
            )
            if year is not None:
                try:
                    deadline = date(year, int(month), int(day))
                    if deadline < today:
                        return "closed", f"deadline_{deadline.isoformat()}"
                except ValueError:
                    pass

    if source == "iel" and (
        "faca login e se candidate" in text or "acesso candidato" in text
    ):
        return "unverified", "application_requires_login"

    for node in soup.select("h1,h2,h3,h4,p,[role='alert']"):
        phrase = plain(node.get_text(" ", strip=True)).strip(" .!:")
        if phrase in OPEN:
            return "open", "explicit_applications_open"

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
    """Select posted URLs from source_postings using the exact source identity."""
    if urls:
        expected = {normalize_url(value) for value in urls}
        if not all(expected) or not expected:
            raise ValueError("Link de consulta invalido")
        matches = []
        for source, job_id, url in conn.execute("""
            SELECT source,source_job_id,url FROM source_postings
            WHERE source IN ('99jobs','bettha','cargill','cia_estagios','iel')
        """):
            if normalize_url(url) in expected:
                matches.append((source, job_id, url))
        absent = expected - {normalize_url(row[2]) for row in matches}
        return matches, sorted(absent)
    if limit <= 0:
        return [], []
    rows = conn.execute("""
        SELECT p.source,p.source_job_id,p.url
        FROM source_postings p
        LEFT JOIN source_availability_checks c
            ON c.source=p.source AND c.source_job_id=p.source_job_id
        WHERE p.is_active=1
          AND p.source IN ('99jobs','bettha','cargill','cia_estagios','iel')
        ORDER BY COALESCE(c.checked_at,'') ASC, p.last_seen_at ASC
        LIMIT ?
    """, (limit * 5,))
    selected = []
    for source, job_id, url in rows:
        if safe_url(source, url):
            selected.append((source, job_id, url))
            if len(selected) >= limit:
                break
    return selected, []


def apply_result(conn, source, job_id, verdict, evidence, *, checked_at=None):
    ensure_schema(conn)
    now = checked_at or datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT verdict FROM source_availability_checks "
        "WHERE source=? AND source_job_id=?", (source, job_id)
    ).fetchone()
    # Never turn a confirmed-closed posting back into an unchecked or
    # ambiguous state due to an HTTP failure, redirect or login wall.
    if existing is not None and existing[0] == "closed" and verdict == "unverified":
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
