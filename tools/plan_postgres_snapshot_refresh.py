"""Read-only plan for refreshing PostgreSQL from a newer SQLite snapshot.

Compares source-native identity, raw hashes, processing versions, and lifecycle
without modifying either database. Does not collect, migrate, or change flags.

Usage (DATABASE_URL must be set):
    python -m tools.plan_postgres_snapshot_refresh \
      --db data/snapshots/main-20261008.db
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from storage.postgres_repository import PostgresOpportunityRepository


SQLITE_FIELDS = """
SELECT source, source_job_id, raw_hash, processing_version,
       last_changed_at, last_seen_at, is_active, miss_count
FROM source_postings
"""


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _index(rows: Iterable[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        key = (str(item["source"]), str(item["source_job_id"]))
        if key in indexed:
            raise ValueError(f"Identidade duplicada: {key!r}")
        indexed[key] = item
    return indexed


def plan_refresh(
    sqlite_rows: Iterable[Any],
    postgres_rows: Iterable[Any],
    *,
    max_samples: int = 5,
) -> dict[str, Any]:
    """Summarize source-native differences without proposing destructive writes."""
    if max_samples < 1:
        raise ValueError("max_samples deve ser >= 1")

    left = _index(sqlite_rows)
    right = _index(postgres_rows)
    left_keys = set(left)
    right_keys = set(right)
    shared = left_keys & right_keys
    sqlite_only = left_keys - right_keys
    postgres_only = right_keys - left_keys

    metrics: Counter[str] = Counter()
    by_source: dict[str, Counter[str]] = {}

    def count(source: str, key: str) -> None:
        by_source.setdefault(source, Counter())[key] += 1

    for source, _ in sqlite_only:
        count(source, "only_sqlite")
        if bool(left[(source, _)]["is_active"]):
            metrics["only_sqlite_active"] += 1
        else:
            metrics["only_sqlite_inactive"] += 1

    for source, _ in postgres_only:
        count(source, "only_postgres")
        if bool(right[(source, _)]["is_active"]):
            metrics["only_postgres_active"] += 1
        else:
            metrics["only_postgres_inactive"] += 1

    example_status: list[dict[str, Any]] = []
    for key in shared:
        s, p = left[key], right[key]
        source = key[0]
        raw_diff = str(s["raw_hash"]) != str(p["raw_hash"])
        version_diff = str(s["processing_version"]) != str(p["processing_version"])
        status_diff = bool(s["is_active"]) != bool(p["is_active"])
        missing_diff = int(s["miss_count"] or 0) != int(p["miss_count"] or 0)
        sqlite_changed = _timestamp(s["last_changed_at"])
        pg_changed = _timestamp(p["last_changed_at"])
        sqlite_seen = _timestamp(s["last_seen_at"])
        pg_seen = _timestamp(p["last_seen_at"])

        if raw_diff:
            metrics["shared_raw_hash_diff"] += 1
            count(source, "shared_raw_hash_diff")
        if version_diff:
            metrics["shared_processing_version_diff"] += 1
        if status_diff:
            metrics["shared_active_status_diff"] += 1
            count(source, "shared_active_status_diff")
            direction = (
                "sqlite_active_postgres_inactive"
                if bool(s["is_active"])
                else "sqlite_inactive_postgres_active"
            )
            metrics[direction] += 1
            if len(example_status) < max_samples:
                example_status.append({
                    "source": source,
                    "source_job_id": key[1],
                    "sqlite_active": bool(s["is_active"]),
                    "postgres_active": bool(p["is_active"]),
                })
        if missing_diff:
            metrics["shared_miss_count_diff"] += 1
        if sqlite_changed is not None and pg_changed is not None:
            if sqlite_changed > pg_changed:
                metrics["shared_sqlite_content_newer"] += 1
            elif sqlite_changed < pg_changed:
                metrics["shared_postgres_content_newer"] += 1
            else:
                metrics["shared_content_same_timestamp"] += 1
        if sqlite_seen is not None and pg_seen is not None:
            if sqlite_seen > pg_seen:
                metrics["shared_sqlite_seen_newer"] += 1
            elif sqlite_seen < pg_seen:
                metrics["shared_postgres_seen_newer"] += 1
            else:
                metrics["shared_seen_same_timestamp"] += 1

    return {
        "sqlite_postings": len(left),
        "postgres_postings": len(right),
        "shared_postings": len(shared),
        "sqlite_only": len(sqlite_only),
        "postgres_only": len(postgres_only),
        "union_postings_if_preserved": len(left_keys | right_keys),
        "sqlite_only_sample": [
            {"source": source, "source_job_id": job_id}
            for source, job_id in sorted(sqlite_only)[:max_samples]
        ],
        "postgres_only_sample": [
            {"source": source, "source_job_id": job_id}
            for source, job_id in sorted(postgres_only)[:max_samples]
        ],
        "metrics": dict(sorted(metrics.items())),
        "per_source": {
            source: dict(sorted(counts.items()))
            for source, counts in sorted(by_source.items())
        },
        "active_status_sample": example_status,
        "read_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, required=True,
        help="Snapshot SQLite a comparar, sem altera-lo.",
    )
    parser.add_argument("--max-samples", type=int, default=5)
    args = parser.parse_args()
    if args.max_samples < 1:
        parser.error("--max-samples deve ser >= 1")
    if not args.db.is_file():
        parser.error(f"Snapshot nao encontrado: {args.db}")
    if not os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL nao configurada.")

    print("CP5 snapshot refresh planning (read-only)")
    sqlite_uri = args.db.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(sqlite_uri, uri=True) as con:
        con.row_factory = sqlite3.Row
        local = con.execute(SQLITE_FIELDS).fetchall()

    with PostgresOpportunityRepository() as repo:
        repo.conn.execute("SET TRANSACTION READ ONLY")
        remote = repo.conn.execute(
            SQLITE_FIELDS.replace(
                "FROM source_postings", "FROM public.source_postings"
            )
        ).fetchall()
        repo.conn.rollback()

    plan = plan_refresh(local, remote, max_samples=args.max_samples)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    print("PLANEJAMENTO CONCLUIDO: nenhum banco foi modificado.")


if __name__ == "__main__":
    main()
