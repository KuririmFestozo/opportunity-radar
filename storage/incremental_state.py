"""Checkpoint 3: persistent discovery and conservative vacancy lifecycle state."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

DEFAULT_MISS_THRESHOLD = 2
DEFAULT_FULL_AUDIT_EVERY = 7


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_columns(conn) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}


def _add_job_column(conn, definition: str) -> None:
    name = definition.split()[0]
    if name not in _job_columns(conn):
        conn.execute(f"ALTER TABLE jobs ADD COLUMN {definition}")


def ensure_incremental_schema(store) -> None:
    """Idempotently migrate the local SQLite store to checkpoint-3 state."""
    conn = store.conn

    _add_job_column(conn, "last_checked_at TEXT")
    _add_job_column(conn, "missing_since TEXT")
    _add_job_column(conn, "inactive_at TEXT")
    _add_job_column(conn, "miss_count INTEGER NOT NULL DEFAULT 0")
    _add_job_column(conn, "seen_count INTEGER NOT NULL DEFAULT 0")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS discovery_state (
            source TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            scope_status TEXT NOT NULL DEFAULT 'catalog',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (source, source_job_id)
        );

        CREATE INDEX IF NOT EXISTS idx_discovery_source
            ON discovery_state(source);

        CREATE INDEX IF NOT EXISTS idx_discovery_scope_status
            ON discovery_state(scope_status);

        CREATE TABLE IF NOT EXISTS collection_scopes (
            source TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            successful_runs INTEGER NOT NULL DEFAULT 0,
            last_full_run INTEGER NOT NULL DEFAULT 0,
            last_coverage TEXT NOT NULL DEFAULT 'unknown',
            last_run_at TEXT,
            PRIMARY KEY (source, scope_key)
        );
        """
    )

    conn.execute(
        """
        UPDATE jobs
        SET last_checked_at = COALESCE(last_checked_at, last_seen_at),
            seen_count = CASE WHEN seen_count < 1 THEN 1 ELSE seen_count END
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO discovery_state(
            source, source_job_id, scope_status,
            first_seen_at, last_seen_at, last_checked_at, seen_count
        )
        SELECT
            source, source_job_id, 'catalog',
            first_seen_at, last_seen_at, last_seen_at, 1
        FROM jobs
        """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO store_meta(key, value)
        VALUES('incremental_schema_version', '3')
        """
    )
    conn.commit()
    if hasattr(store, "_cache"):
        store._cache = None


def known_discovery_ids(store, source: str, *, prefix: str | None = None) -> set[str]:
    sql = "SELECT source_job_id FROM discovery_state WHERE source = ?"
    args: list[object] = [source]
    if prefix is not None:
        sql += " AND source_job_id LIKE ?"
        args.append(prefix + "%")
    return {str(row[0]) for row in store.conn.execute(sql, args).fetchall()}


def record_discoveries(
    store,
    source: str,
    source_job_ids: Iterable[str],
    *,
    scope_status: str = "catalog",
    seen_at: str | None = None,
) -> int:
    """Remember IDs even when they are intentionally not stored as catalog jobs."""
    now = seen_at or _utcnow()
    ids = sorted({str(value) for value in source_job_ids if str(value)})
    if not ids:
        return 0

    rows = [
        (source, source_job_id, scope_status, now, now, now, 1)
        for source_job_id in ids
    ]
    store.conn.executemany(
        """
        INSERT INTO discovery_state(
            source, source_job_id, scope_status,
            first_seen_at, last_seen_at, last_checked_at, seen_count
        )
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_job_id) DO UPDATE SET
            scope_status = CASE
                WHEN discovery_state.scope_status = 'catalog'
                  OR excluded.scope_status = 'catalog'
                    THEN 'catalog'
                ELSE excluded.scope_status
            END,
            last_seen_at = excluded.last_seen_at,
            last_checked_at = excluded.last_checked_at,
            seen_count = discovery_state.seen_count + 1
        """,
        rows,
    )
    return len(ids)


def mark_seen_ids(
    store,
    source: str,
    source_job_ids: Iterable[str],
    *,
    scope_status: str = "catalog",
    seen_at: str | None = None,
) -> dict:
    """Reset missing/inactive state for IDs that were positively observed."""
    now = seen_at or _utcnow()
    ids = sorted({str(value) for value in source_job_ids if str(value)})
    if not ids:
        return {"seen": 0, "reopened": 0}

    record_discoveries(
        store,
        source,
        ids,
        scope_status=scope_status,
        seen_at=now,
    )

    reopened = 0
    for source_job_id in ids:
        row = store.conn.execute(
            """
            SELECT is_active, miss_count
            FROM jobs
            WHERE source = ? AND source_job_id = ?
            """,
            (source, source_job_id),
        ).fetchone()
        if row is not None and (
            not bool(row["is_active"]) or int(row["miss_count"] or 0) > 0
        ):
            reopened += 1

    store.conn.executemany(
        """
        UPDATE jobs
        SET last_seen_at = ?,
            last_checked_at = ?,
            seen_count = seen_count + 1,
            miss_count = 0,
            missing_since = NULL,
            inactive_at = NULL,
            is_active = 1
        WHERE source = ? AND source_job_id = ?
        """,
        [(now, now, source, source_job_id) for source_job_id in ids],
    )
    return {"seen": len(ids), "reopened": reopened}


def mark_seen_jobs(store, jobs, *, seen_at: str | None = None) -> dict:
    grouped: dict[str, set[str]] = defaultdict(set)
    for job in jobs:
        grouped[str(job.source)].add(str(job.source_job_id))

    total_seen = 0
    reopened = 0
    for source, ids in grouped.items():
        result = mark_seen_ids(
            store,
            source,
            ids,
            scope_status="catalog",
            seen_at=seen_at,
        )
        total_seen += result["seen"]
        reopened += result["reopened"]
    return {"seen": total_seen, "reopened": reopened}


def reconcile_scope(
    store,
    source: str,
    seen_source_job_ids: Iterable[str],
    *,
    prefix: str | None = None,
    coverage: str = "partial",
    miss_threshold: int = DEFAULT_MISS_THRESHOLD,
    checked_at: str | None = None,
) -> dict:
    """Advance lifecycle only after a provably complete scope scan."""
    now = checked_at or _utcnow()
    seen = {str(value) for value in seen_source_job_ids if str(value)}
    result = {
        "coverage": coverage,
        "checked": 0,
        "seen": len(seen),
        "new_missing": 0,
        "inactivated": 0,
        "skipped": coverage != "complete",
    }
    if coverage != "complete":
        return result

    threshold = max(2, int(miss_threshold or DEFAULT_MISS_THRESHOLD))
    sql = (
        "SELECT source_job_id, is_active, miss_count, missing_since "
        "FROM jobs WHERE source = ?"
    )
    args: list[object] = [source]
    if prefix is not None:
        sql += " AND source_job_id LIKE ?"
        args.append(prefix + "%")

    rows = store.conn.execute(sql, args).fetchall()
    result["checked"] = len(rows)

    for row in rows:
        source_job_id = str(row["source_job_id"])
        if source_job_id in seen:
            store.conn.execute(
                """
                UPDATE jobs
                SET last_checked_at = ?
                WHERE source = ? AND source_job_id = ?
                """,
                (now, source, source_job_id),
            )
            continue

        if not bool(row["is_active"]):
            store.conn.execute(
                """
                UPDATE jobs
                SET last_checked_at = ?
                WHERE source = ? AND source_job_id = ?
                """,
                (now, source, source_job_id),
            )
            continue

        old_miss = int(row["miss_count"] or 0)
        new_miss = old_miss + 1
        inactive = new_miss >= threshold
        if old_miss == 0:
            result["new_missing"] += 1
        if inactive:
            result["inactivated"] += 1

        store.conn.execute(
            """
            UPDATE jobs
            SET last_checked_at = ?,
                miss_count = ?,
                missing_since = COALESCE(missing_since, ?),
                inactive_at = CASE
                    WHEN ? THEN COALESCE(inactive_at, ?)
                    ELSE inactive_at
                END,
                is_active = CASE WHEN ? THEN 0 ELSE is_active END
            WHERE source = ? AND source_job_id = ?
            """,
            (
                now,
                new_miss,
                now,
                int(inactive),
                now,
                int(inactive),
                source,
                source_job_id,
            ),
        )
    return result


def needs_full_audit(
    store,
    source: str,
    scope_key: str,
    *,
    every_runs: int = DEFAULT_FULL_AUDIT_EVERY,
) -> bool:
    """Force an occasional full scan after several partial incremental runs."""
    every = max(2, int(every_runs or DEFAULT_FULL_AUDIT_EVERY))
    row = store.conn.execute(
        """
        SELECT successful_runs, last_full_run
        FROM collection_scopes
        WHERE source = ? AND scope_key = ?
        """,
        (source, scope_key),
    ).fetchone()
    if row is None:
        return False
    runs = int(row["successful_runs"] or 0)
    last_full = int(row["last_full_run"] or 0)
    return (runs - last_full) >= (every - 1)


def finish_scope_run(
    store,
    source: str,
    scope_key: str,
    *,
    coverage: str,
    finished_at: str | None = None,
) -> None:
    now = finished_at or _utcnow()
    row = store.conn.execute(
        """
        SELECT successful_runs, last_full_run
        FROM collection_scopes
        WHERE source = ? AND scope_key = ?
        """,
        (source, scope_key),
    ).fetchone()
    old_runs = int(row["successful_runs"] or 0) if row else 0
    old_full = int(row["last_full_run"] or 0) if row else 0
    runs = old_runs + 1
    last_full = runs if coverage == "complete" else old_full

    store.conn.execute(
        """
        INSERT INTO collection_scopes(
            source, scope_key, successful_runs,
            last_full_run, last_coverage, last_run_at
        )
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, scope_key) DO UPDATE SET
            successful_runs = excluded.successful_runs,
            last_full_run = excluded.last_full_run,
            last_coverage = excluded.last_coverage,
            last_run_at = excluded.last_run_at
        """,
        (source, scope_key, runs, last_full, coverage, now),
    )


def lifecycle_stats(store) -> dict:
    conn = store.conn
    active = int(
        conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1").fetchone()[0]
    )
    missing = int(
        conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active = 1 AND miss_count > 0"
        ).fetchone()[0]
    )
    inactive = int(
        conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 0").fetchone()[0]
    )
    discoveries = int(
        conn.execute("SELECT COUNT(*) FROM discovery_state").fetchone()[0]
    )
    out_of_scope = int(
        conn.execute(
            "SELECT COUNT(*) FROM discovery_state "
            "WHERE scope_status = 'out_of_scope'"
        ).fetchone()[0]
    )
    return {
        "active": active,
        "missing": missing,
        "inactive": inactive,
        "discoveries": discoveries,
        "out_of_scope_discoveries": out_of_scope,
    }
