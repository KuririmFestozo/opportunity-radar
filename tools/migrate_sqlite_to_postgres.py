"""Migrate the CP4 SQLite catalog into PostgreSQL/PostGIS (CP5-A).

The command is intentionally explicit: SQLite remains the production backend
until later CP5 checkpoints prove parity and port writes/lifecycle.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.job_store import DEFAULT_DB_PATH, JobStore
from storage.unified_schema import sync_unified_persistence

MIGRATION_PATH = ROOT / "database" / "migrations" / "0001_cp5_catalog.sql"
TABLES = (
    "opportunities",
    "source_postings",
    "opportunity_course_scores",
    "opportunity_intents",
    "discovery_state",
    "collection_scopes",
)


def _prepare_sqlite(path: Path) -> None:
    """Bring a local DB to the latest CP4 relational state before exporting."""
    with JobStore(path) as store:
        sync_unified_persistence(store)


def _snapshot(path: Path) -> dict[str, list[dict[str, Any]]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        data: dict[str, list[dict[str, Any]]] = {}
        for table in TABLES:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            data[table] = [dict(row) for row in rows]
        return data
    finally:
        conn.close()


def _counts(data: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {table: len(data.get(table, [])) for table in TABLES}


def _apply_schema(conn: psycopg.Connection) -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    # Parameterless psycopg execution uses PostgreSQL's simple-query path and
    # accepts the multi-statement migration, including the SQL function body.
    conn.execute(sql)


def _reset_target(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        TRUNCATE TABLE
            public.opportunity_course_scores,
            public.opportunity_intents,
            public.source_postings,
            public.opportunities,
            public.discovery_state,
            public.collection_scopes
        CASCADE
        """
    )


def _migrate_opportunities(conn, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    sql = """
        INSERT INTO public.opportunities(
            id, company, title, description, location_text, location,
            location_confidence, workplace_type, employment_type, salary,
            published_at, canonical_url, created_at, updated_at
        )
        VALUES(
            %s, %s, %s, %s, %s,
            CASE
                WHEN %s IS NULL OR %s IS NULL THEN NULL
                ELSE extensions.st_setsrid(
                    extensions.st_makepoint(%s, %s), 4326
                )::extensions.geography
            END,
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT(id) DO UPDATE SET
            company = excluded.company,
            title = excluded.title,
            description = excluded.description,
            location_text = excluded.location_text,
            location = excluded.location,
            location_confidence = excluded.location_confidence,
            workplace_type = excluded.workplace_type,
            employment_type = excluded.employment_type,
            salary = excluded.salary,
            published_at = excluded.published_at,
            canonical_url = excluded.canonical_url,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at
    """
    params = []
    for row in rows:
        latitude = row.get("latitude")
        longitude = row.get("longitude")
        params.append(
            (
                row["id"],
                row.get("company") or "",
                row.get("title") or "",
                row.get("description") or "",
                row.get("location_text") or "",
                latitude,
                longitude,
                longitude,
                latitude,
                row.get("location_confidence"),
                row.get("workplace_type"),
                row.get("employment_type"),
                row.get("salary"),
                row.get("published_at"),
                row.get("canonical_url"),
                row["created_at"],
                row["updated_at"],
            )
        )
    with conn.cursor() as cur:
        cur.executemany(sql, params)


def _migrate_source_postings(conn, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    sql = """
        INSERT INTO public.source_postings(
            source, source_job_id, opportunity_id, url, source_type,
            normalized_job_json, raw_hash, processing_version,
            first_seen_at, last_seen_at, last_checked_at, last_changed_at,
            is_active, missing_since, inactive_at, miss_count, seen_count,
            association_method, associated_at
        )
        VALUES(
            %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT(source, source_job_id) DO UPDATE SET
            opportunity_id = excluded.opportunity_id,
            url = excluded.url,
            source_type = excluded.source_type,
            normalized_job_json = excluded.normalized_job_json,
            raw_hash = excluded.raw_hash,
            processing_version = excluded.processing_version,
            first_seen_at = excluded.first_seen_at,
            last_seen_at = excluded.last_seen_at,
            last_checked_at = excluded.last_checked_at,
            last_changed_at = excluded.last_changed_at,
            is_active = excluded.is_active,
            missing_since = excluded.missing_since,
            inactive_at = excluded.inactive_at,
            miss_count = excluded.miss_count,
            seen_count = excluded.seen_count,
            association_method = excluded.association_method,
            associated_at = excluded.associated_at
    """
    params = [
        (
            row["source"],
            row["source_job_id"],
            row["opportunity_id"],
            row.get("url") or "",
            row.get("source_type") or "official_api",
            row.get("normalized_job_json") or "{}",
            row["raw_hash"],
            row["processing_version"],
            row["first_seen_at"],
            row["last_seen_at"],
            row.get("last_checked_at"),
            row["last_changed_at"],
            bool(row.get("is_active")),
            row.get("missing_since"),
            row.get("inactive_at"),
            int(row.get("miss_count") or 0),
            int(row.get("seen_count") or 0),
            row.get("association_method") or "identity",
            row.get("associated_at"),
        )
        for row in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, params)


def _migrate_course_scores(conn, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.opportunity_course_scores(
                opportunity_id, course_id, score
            )
            VALUES(%s, %s, %s)
            ON CONFLICT(opportunity_id, course_id) DO UPDATE
            SET score = excluded.score
            """,
            [
                (row["opportunity_id"], row["course_id"], int(row["score"]))
                for row in rows
            ],
        )


def _migrate_intents(conn, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.opportunity_intents(opportunity_id, intent_id)
            VALUES(%s, %s)
            ON CONFLICT(opportunity_id, intent_id) DO NOTHING
            """,
            [(row["opportunity_id"], row["intent_id"]) for row in rows],
        )


def _migrate_discovery(conn, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.discovery_state(
                source, source_job_id, scope_status,
                first_seen_at, last_seen_at, last_checked_at, seen_count
            )
            VALUES(%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(source, source_job_id) DO UPDATE SET
                scope_status = excluded.scope_status,
                first_seen_at = excluded.first_seen_at,
                last_seen_at = excluded.last_seen_at,
                last_checked_at = excluded.last_checked_at,
                seen_count = excluded.seen_count
            """,
            [
                (
                    row["source"],
                    row["source_job_id"],
                    row.get("scope_status") or "catalog",
                    row["first_seen_at"],
                    row["last_seen_at"],
                    row["last_checked_at"],
                    int(row.get("seen_count") or 1),
                )
                for row in rows
            ],
        )


def _migrate_scopes(conn, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO public.collection_scopes(
                source, scope_key, successful_runs,
                last_full_run, last_coverage, last_run_at
            )
            VALUES(%s, %s, %s, %s, %s, %s)
            ON CONFLICT(source, scope_key) DO UPDATE SET
                successful_runs = excluded.successful_runs,
                last_full_run = excluded.last_full_run,
                last_coverage = excluded.last_coverage,
                last_run_at = excluded.last_run_at
            """,
            [
                (
                    row["source"],
                    row["scope_key"],
                    int(row.get("successful_runs") or 0),
                    int(row.get("last_full_run") or 0),
                    row.get("last_coverage") or "unknown",
                    row.get("last_run_at"),
                )
                for row in rows
            ],
        )


def _target_counts(conn) -> dict[str, int]:
    counts = {}
    for table in TABLES:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM public.{table}"
        ).fetchone()
        counts[table] = int(row["n"])
    return counts


def migrate(
    sqlite_path: Path,
    dsn: str,
    *,
    reset_target: bool = False,
) -> tuple[dict[str, int], dict[str, int]]:
    _prepare_sqlite(sqlite_path)
    data = _snapshot(sqlite_path)
    source_counts = _counts(data)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        _apply_schema(conn)
        if reset_target:
            _reset_target(conn)

        _migrate_opportunities(conn, data["opportunities"])
        _migrate_source_postings(conn, data["source_postings"])
        _migrate_course_scores(conn, data["opportunity_course_scores"])
        _migrate_intents(conn, data["opportunity_intents"])
        _migrate_discovery(conn, data["discovery_state"])
        _migrate_scopes(conn, data["collection_scopes"])

        target_counts = _target_counts(conn)
        conn.commit()

    return source_counts, target_counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Opportunity Radar CP4 SQLite state to PostgreSQL."
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL connection string. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare/inspect SQLite and print row counts without connecting.",
    )
    parser.add_argument(
        "--reset-target",
        action="store_true",
        help="TRUNCATE CP5 catalog tables before inserting the snapshot.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.db)
    _prepare_sqlite(sqlite_path)
    data = _snapshot(sqlite_path)
    source_counts = _counts(data)

    print("CP5-A SQLite -> PostgreSQL")
    print(f"SQLite: {sqlite_path}")
    for table, count in source_counts.items():
        print(f"{table}: {count}")

    if args.dry_run:
        print("Dry-run: OK (nenhuma conexão PostgreSQL realizada).")
        return

    dsn = str(args.database_url or "").strip()
    if not dsn:
        raise SystemExit(
            "DATABASE_URL não configurada. Use --dry-run ou forneça a conexão."
        )

    source_counts, target_counts = migrate(
        sqlite_path,
        dsn,
        reset_target=args.reset_target,
    )

    print("PostgreSQL:")
    for table, count in target_counts.items():
        print(f"{table}: {count}")

    mismatches = {
        table: (source_counts[table], target_counts[table])
        for table in TABLES
        if source_counts[table] != target_counts[table]
    }
    if mismatches:
        print(f"Paridade: FAILED {mismatches}")
        raise SystemExit(1)

    print("Paridade de contagens: OK")


if __name__ == "__main__":
    main()
