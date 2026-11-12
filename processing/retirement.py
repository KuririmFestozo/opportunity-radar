"""Two-stage retirement of genuinely unavailable source postings.

A closed application message deactivates immediately (existing audit policy).
Repeated official vacancy 404/410 responses are *not* proof on their own:
three checks on distinct UTC days are needed to deactivate, and five checks
spanning 14 days before physical deletion. Timeouts, CAPTCHAs, 403/429,
redirects and unrecognized URLs never count.

A permanent tombstone prevents the next discovery cycle from silently restoring
records deleted on purpose. Orphan opportunities are deleted only when they
have no remaining postings or personal/application references.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from processing.source_availability import apply_result, probe, safe_url

MIN_INACTIVE_CHECKS = 3
MIN_DELETE_CHECKS = 5
MIN_DELETE_AGE_DAYS = 14
PERSONAL_TABLES = (
    "web_favorites", "web_applications",
    "web_device_favorites", "web_device_applications",
)


def _exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posting_retirement_checks (
            source TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            first_bad_day TEXT,
            last_checked_day TEXT NOT NULL,
            bad_checks INTEGER NOT NULL DEFAULT 0,
            disabled_by_missing INTEGER NOT NULL DEFAULT 0,
            last_evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(source,source_job_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_retirement_checks_bad
        ON posting_retirement_checks(bad_checks,last_checked_day)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS purged_postings (
            source TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            purged_at TEXT NOT NULL,
            evidence TEXT NOT NULL,
            PRIMARY KEY(source,source_job_id)
        )
    """)


def purged_keys(conn) -> set[tuple[str, str]]:
    if not _exists(conn, "purged_postings"):
        return set()
    return {(str(s), str(j)) for s, j in conn.execute(
        "SELECT source,source_job_id FROM purged_postings"
    )}


def _utc_day(when: str | datetime | date) -> str:
    if isinstance(when, date):
        return when.isoformat()[:10]
    try:
        day = date.fromisoformat(str(when)[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid UTC check day: {when!r}") from exc
    return day.isoformat()


def _missing_signal(source: str, url: str, evidence: str) -> bool:
    if evidence not in ("http_404", "http_410"):
        return False
    if not safe_url(source, url):
        return False
    # Old /jobs/<id> Gupy URLs can disappear after Gupy changes the link
    # format even while the vacancy continues accepting applications.
    if source in ("gupy_global", "gupy_api", "gupy_public"):
        if urlsplit(url).path.startswith("/jobs/"):
            return False
    return True


def observe(conn, source: str, job_id: str, url: str, verdict: str,
            evidence: str, *, checked_at: str) -> int:
    """Record at most one failing verification per UTC day; return inactivations.

    Failures must be consecutive *observations* on different dates; an open
    result, server outage or login wall resets the streak. The evidence has
    to match an official URL belonging to this source.
    """
    ensure_schema(conn)
    source, job_id = str(source), str(job_id)
    day = _utc_day(checked_at)
    if conn.execute(
        "SELECT 1 FROM purged_postings WHERE source=? AND source_job_id=?",
        (source, job_id),
    ).fetchone():
        return 0
    bad = (verdict == "closed" or _missing_signal(source, url, evidence))
    prior = conn.execute("""
        SELECT first_bad_day,last_checked_day,bad_checks,disabled_by_missing
        FROM posting_retirement_checks WHERE source=? AND source_job_id=?
    """, (source, job_id)).fetchone()
    if prior and prior[1] == day:
        # Different jobs/routes may be examined twice on a given day.
        # Never grant two strikes for the same calendar day.
        return 0
    first = (str(prior[0]) if bad and prior and prior[2] and prior[0] else day) if bad else None
    strikes = (int(prior[2]) if prior else 0) + 1 if bad else 0
    conn.execute("""
        INSERT INTO posting_retirement_checks
            (source,source_job_id,first_bad_day,last_checked_day,bad_checks,last_evidence)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(source,source_job_id) DO UPDATE SET
            first_bad_day=excluded.first_bad_day,
            last_checked_day=excluded.last_checked_day,
            bad_checks=excluded.bad_checks,
            last_evidence=excluded.last_evidence
    """, (source, job_id, first, day, strikes, evidence))
    if verdict == "open" and prior and prior[3]:
        # An explicitly reopened vacancy can reverse a previous *soft* HTTP
        # 404/410 deactivation. Never revive manually/explicitly closed jobs.
        closed = False
        if _exists(conn, "source_availability_checks"):
            closed |= conn.execute("""
                SELECT 1 FROM source_availability_checks
                WHERE source=? AND source_job_id=? AND verdict='closed'
            """, (source, job_id)).fetchone() is not None
        if _exists(conn, "gupy_url_checks"):
            closed |= conn.execute("""
                SELECT 1 FROM gupy_url_checks
                WHERE source=? AND source_job_id=? AND verdict='closed'
            """, (source, job_id)).fetchone() is not None
        if not closed:
            conn.execute("""
                UPDATE jobs SET is_active=1, inactive_at=NULL,
                    missing_since=NULL, miss_count=0
                WHERE source=? AND source_job_id=?
            """, (source, job_id))
            conn.execute("""
                UPDATE source_postings SET is_active=1, inactive_at=NULL
                WHERE source=? AND source_job_id=?
            """, (source, job_id))
            conn.execute("""
                UPDATE posting_retirement_checks SET disabled_by_missing=0
                WHERE source=? AND source_job_id=?
            """, (source, job_id))
    if not bad or verdict == "closed" or strikes < MIN_INACTIVE_CHECKS:
        return 0
    now = checked_at
    count = conn.execute("""
        UPDATE jobs SET is_active=0,
            inactive_at=COALESCE(inactive_at,?),
            last_checked_at=?, missing_since=COALESCE(missing_since,?),
            miss_count=MAX(miss_count,?)
        WHERE source=? AND source_job_id=? AND is_active=1
    """, (now, now, now, strikes, source, job_id)).rowcount
    if count:
        conn.execute("""
            UPDATE posting_retirement_checks SET disabled_by_missing=1
            WHERE source=? AND source_job_id=?
        """, (source, job_id))
    if _exists(conn, "source_postings"):
        # Keep the relational shadow's lifecycle fields aligned with legacy
        # jobs. Older test/demo databases may lack the optional miss columns.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(source_postings)")}
        if {"missing_since", "miss_count"} <= columns:
            conn.execute("""
                UPDATE source_postings SET is_active=0,
                    inactive_at=COALESCE(inactive_at,?), last_checked_at=?,
                    missing_since=COALESCE(missing_since,?),
                    miss_count=MAX(miss_count,?)
                WHERE source=? AND source_job_id=? AND is_active=1
            """, (now, now, now, strikes, source, job_id))
        else:
            conn.execute("""
                UPDATE source_postings SET is_active=0,
                    inactive_at=COALESCE(inactive_at,?), last_checked_at=?
                WHERE source=? AND source_job_id=? AND is_active=1
            """, (now, now, source, job_id))
    return count


def _recent_audit_signals(conn, today: str) -> list[tuple[str, str, str, str, str, str]]:
    """Collect observations from today's existing Gupy and generic audits."""
    entries = []
    if _exists(conn, "source_availability_checks"):
        entries += conn.execute("""
            SELECT a.source,a.source_job_id,p.url,a.verdict,a.evidence,a.checked_at
            FROM source_availability_checks a
            JOIN source_postings p ON p.source=a.source
                AND p.source_job_id=a.source_job_id
            WHERE substr(a.checked_at,1,10)=?
        """, (today,)).fetchall()
    if _exists(conn, "gupy_url_checks"):
        entries += [
            (s, j, url, "closed", evidence, checked)
            for s, j, url, evidence, checked in conn.execute("""
                SELECT g.source,g.source_job_id,p.url,g.evidence,g.checked_at
                FROM gupy_url_checks g JOIN source_postings p
                  ON p.source=g.source AND p.source_job_id=g.source_job_id
                WHERE g.verdict='closed' AND substr(g.checked_at,1,10)=?
            """, (today,))
        ]
    # If two independent auditors checked the same link today, use explicit
    # closure evidence first; never double-count the date.
    entries.sort(key=lambda item: (item[3] != "closed", item[0], item[1]))
    return entries


def _followup_candidates(conn, today: str, limit: int):
    if limit <= 0:
        return []
    # Use only concrete official vacancy pages. A closed posting can be
    # retried while inactive; otherwise its status would never accrue proof.
    has_av = _exists(conn, "source_availability_checks")
    has_gp = _exists(conn, "gupy_url_checks")
    av_join = ("LEFT JOIN source_availability_checks a ON "
               "a.source=p.source AND a.source_job_id=p.source_job_id" if has_av else "")
    gp_join = ("LEFT JOIN gupy_url_checks g ON "
               "g.source=p.source AND g.source_job_id=p.source_job_id" if has_gp else "")
    av_term = "a.verdict='closed' OR a.evidence IN ('http_404','http_410')" if has_av else "0"
    gp_term = "g.verdict='closed'" if has_gp else "0"
    rows = conn.execute(f"""
        SELECT p.source,p.source_job_id,p.url
        FROM source_postings p
        LEFT JOIN posting_retirement_checks r ON
            r.source=p.source AND r.source_job_id=p.source_job_id
        {av_join} {gp_join}
        WHERE (r.bad_checks>0 OR {av_term} OR {gp_term})
          AND (r.last_checked_day IS NULL OR r.last_checked_day<?)
          AND NOT EXISTS (
              SELECT 1 FROM purged_postings x
              WHERE x.source=p.source AND x.source_job_id=p.source_job_id
          )
        ORDER BY CASE WHEN r.bad_checks>0 THEN 0 ELSE 1 END,
                 COALESCE(r.last_checked_day,'') ASC, p.source,p.source_job_id
        LIMIT ?
    """, (today, max(limit * 8, limit))).fetchall()
    return [(str(s), str(j), str(url)) for s, j, url in rows
            if safe_url(str(s), str(url))][:limit]


def _personal_reference(conn, opportunity_id: str) -> bool:
    # Protect *any* external table with an opportunity_id relationship, not
    # only the four expected web tables. The two classification tables are
    # safe to delete via ON DELETE CASCADE when the parent is truly orphaned.
    ignore = {"source_postings", "opportunity_course_scores", "opportunity_intents"}
    for (table,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ):
        if table in ignore:
            continue
        cols = {x[1] for x in conn.execute('PRAGMA table_info("' + table.replace('"', '""') + '")')}
        if "opportunity_id" not in cols:
            continue
        quoted = '"' + table.replace('"', '""') + '"'
        if conn.execute(f'SELECT 1 FROM {quoted} WHERE opportunity_id=? LIMIT 1',
                        (opportunity_id,)).fetchone():
            return True
    return False


def purge_existing(conn, source: str, job_id: str) -> tuple[bool, bool]:
    """Remove one posting and its orphan parent, unless personally referenced.

    Returns (removed_posting, protected_by_user_reference). Called only for
    already-confirmed tombstones/eligible deletes, under a transaction.
    """
    row = conn.execute("""
        SELECT opportunity_id FROM source_postings
        WHERE source=? AND source_job_id=?
    """, (source, job_id)).fetchone()
    if row:
        opp_id = str(row[0])
        if _personal_reference(conn, opp_id):
            conn.execute("""
                UPDATE source_postings SET is_active=0
                WHERE source=? AND source_job_id=?
            """, (source, job_id))
            conn.execute("""
                UPDATE jobs SET is_active=0
                WHERE source=? AND source_job_id=?
            """, (source, job_id))
            return False, True
        conn.execute("DELETE FROM source_postings WHERE source=? AND source_job_id=?",
                     (source, job_id))
        conn.execute("DELETE FROM jobs WHERE source=? AND source_job_id=?",
                     (source, job_id))
        if conn.execute(
            "SELECT 1 FROM source_postings WHERE opportunity_id=? LIMIT 1",
            (opp_id,),
        ).fetchone() is None:
            conn.execute("DELETE FROM opportunities WHERE id=?", (opp_id,))
        return True, False
    # Some historical legacy jobs were never mirrored; they have no FK.
    deleted = conn.execute("DELETE FROM jobs WHERE source=? AND source_job_id=?",
                           (source, job_id)).rowcount
    return bool(deleted), False


def _eligible(conn, today: str, *, max_items: int) -> list[tuple[str, str, str]]:
    if max_items <= 0:
        return []
    rows = conn.execute("""
        SELECT p.source,p.source_job_id,r.last_evidence
        FROM posting_retirement_checks r
        JOIN source_postings p ON p.source=r.source AND p.source_job_id=r.source_job_id
        JOIN jobs j ON j.source=r.source AND j.source_job_id=r.source_job_id
        WHERE r.bad_checks>=? AND r.first_bad_day IS NOT NULL
          AND julianday(?) - julianday(r.first_bad_day)>=?
          AND p.is_active=0 AND j.is_active=0
          AND NOT EXISTS (
              SELECT 1 FROM purged_postings x
              WHERE x.source=p.source AND x.source_job_id=p.source_job_id
          )
        ORDER BY r.first_bad_day,p.source,p.source_job_id LIMIT ?
    """, (MIN_DELETE_CHECKS, today, MIN_DELETE_AGE_DAYS, max_items))
    return [(str(s), str(j), str(e)) for s, j, e in rows]


def _backup(conn, db_path: str | Path) -> str:
    target = Path(db_path).resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    folder = target.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = folder / f"{target.stem}-before-retirement-{stamp}.db"
    with sqlite3.connect(output) as backup:
        conn.backup(backup)
    return str(output)


def run_daily_retirement(conn: sqlite3.Connection, *, db_path: str | Path,
                         recheck_limit: int = 120, delete_limit: int = 30,
                         workers: int = 6, now: datetime | None = None,
                         allow_delete: bool = True) -> dict:
    """Apply daily evidence checks and guarded physical retirement.

    Called after the collector and relational schema sync. Every deletion
    writes a tombstone and a SQLite backup; no in-memory guessed absence
    causes a deletion. Zero deletion and no backup is the common case.
    """
    if not (0 <= recheck_limit <= 2000 and 0 <= delete_limit <= 1000 and
            1 <= workers <= 12):
        raise ValueError("Limits out of range")
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).date().isoformat()
    ensure_schema(conn)
    counters = Counter()
    # The standard audits just ran. Count their evidence once per day.
    for s, j, url, verdict, evidence, checked in _recent_audit_signals(conn, today):
        counters["inactivated"] += observe(
            conn, s, j, url, verdict, evidence, checked_at=checked
        )
        counters["new_observations"] += 1
    conn.commit()

    candidates = _followup_candidates(conn, today, recheck_limit)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(probe, s, url): (s, j, url) for s, j, url in candidates
        }
        for future in as_completed(futures):
            s, j, url = futures[future]
            try:
                verdict, evidence = future.result()
            except Exception:
                verdict, evidence = "unverified", "unexpected_check_error"
            checked = now.isoformat()
            counters["inactivated"] += apply_result(
                conn, s, j, verdict, evidence, checked_at=checked
            )
            counters["inactivated"] += observe(
                conn, s, j, url, verdict, evidence, checked_at=checked
            )
            counters["rechecked"] += 1
            counters[verdict] += 1
    conn.commit()

    due = _eligible(conn, today, max_items=delete_limit * 20)
    counters["ready_to_purge"] = len(due)
    # Never create a backup just to retry links attached to user data.
    # Skipping protected rows here also prevents them from starving other
    # ready-to-delete postings at the top of the retirement queue.
    eligible = []
    for source, job_id, evidence in due:
        ref = conn.execute("""
            SELECT opportunity_id FROM source_postings
            WHERE source=? AND source_job_id=?
        """, (source, job_id)).fetchone()
        if ref and _personal_reference(conn, str(ref[0])):
            counters["protected"] += 1
            continue
        eligible.append((source, job_id, evidence))
        if len(eligible) >= delete_limit:
            break
    if eligible and allow_delete:
        counters["backup"] = _backup(conn, db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            for s, j, evidence in eligible:
                removed, protected = purge_existing(conn, s, j)
                if protected:
                    counters["protected"] += 1
                    continue
                # Retain source/job ID forever to block reappearance during
                # the next import or collector run, even after deleting jobs.
                conn.execute("""
                    INSERT OR IGNORE INTO purged_postings
                        (source,source_job_id,purged_at,evidence)
                    VALUES (?,?,?,?)
                """, (s, j, now.isoformat(), evidence))
                counters["purged"] += int(removed)
            problems = conn.execute("PRAGMA foreign_key_check").fetchone()
            if problems is not None:
                raise sqlite3.IntegrityError("Foreign keys invalid after deletion")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "new_observations": counters["new_observations"],
        "rechecked": counters["rechecked"],
        "inactivated": counters["inactivated"],
        "ready_to_purge": counters["ready_to_purge"],
        "purged": counters["purged"],
        "protected": counters["protected"],
        "backup": counters.get("backup"),
    }


def import_tombstones(conn: sqlite3.Connection) -> dict:
    """Apply audited deletions from incoming SQLite during web catalog sync.

    Only source/job keys from the incoming *purged_postings* table may cause
    a deletion. Existing web favorites and applications prevent erasure;
    linked posting remains as inactive history for those users.
    """
    if not conn.execute(
        "SELECT 1 FROM incoming.sqlite_master WHERE type='table' AND name='purged_postings'"
    ).fetchone():
        return {"imported": 0, "removed": 0, "protected": 0}
    ensure_schema(conn)
    before = conn.execute("SELECT COUNT(*) FROM purged_postings").fetchone()[0]
    conn.execute("""
        INSERT OR IGNORE INTO main.purged_postings(source,source_job_id,purged_at,evidence)
        SELECT source,source_job_id,purged_at,evidence
        FROM incoming.purged_postings WHERE 1=1
    """)
    removed, protected = 0, 0
    for source, job_id in conn.execute(
        "SELECT source,source_job_id FROM main.purged_postings"
    ).fetchall():
        yes, blocked = purge_existing(conn, str(source), str(job_id))
        removed += int(yes)
        protected += int(blocked)
    after = conn.execute("SELECT COUNT(*) FROM purged_postings").fetchone()[0]
    return {"imported": after - before, "removed": removed, "protected": protected}


def filter_purged(jobs, purged: set[tuple[str, str]]):
    """Prevent future collectors from reintroducing intentionally purged IDs."""
    kept = [j for j in jobs if (j.source, str(j.source_job_id)) not in purged]
    return kept, len(jobs) - len(kept)
