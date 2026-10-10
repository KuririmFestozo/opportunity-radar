"""Read-only SQLite/PostgreSQL overlap comparison for different snapshots.

The PostgreSQL catalog may contain newer postings absent from a local SQLite
snapshot. Only records present in *both* catalogs are compared field by field.

Run (with DATABASE_URL already configured):
    python -m tools.validate_backend_overlap

No writes, collection, migrations, or synchronization are performed.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from models.job import Job
from storage.job_store import DEFAULT_DB_PATH
from storage.postgres_repository import PostgresOpportunityRepository
from storage.sqlite_repository import SQLiteOpportunityRepository
from tools.validate_backend_parity import _by_opportunity_id, job_signature


def compare_overlap(
    sqlite_jobs: list[Job],
    postgres_jobs: list[Job],
    *,
    max_samples: int = 5,
) -> dict[str, Any]:
    """Compare equal opportunity IDs, allowing new PostgreSQL-only records."""
    if max_samples < 1:
        raise ValueError("max_samples must be positive")

    sqlite_map = _by_opportunity_id(sqlite_jobs)
    postgres_map = _by_opportunity_id(postgres_jobs)

    shared_ids = set(sqlite_map) & set(postgres_map)
    sqlite_only = sorted(set(sqlite_map) - set(postgres_map))
    postgres_only = sorted(set(postgres_map) - set(sqlite_map))

    changed_fields = Counter()
    mismatch_count = 0
    mismatches = []
    for opportunity_id in sorted(shared_ids):
        original = job_signature(sqlite_map[opportunity_id])
        migrated = job_signature(postgres_map[opportunity_id])
        differing = sorted(
            field for field in original if original[field] != migrated[field]
        )
        if not differing:
            continue
        mismatch_count += 1
        changed_fields.update(differing)
        if len(mismatches) < max_samples:
            mismatches.append({
                "opportunity_id": opportunity_id,
                "different_fields": differing,
            })

    return {
        "ok": bool(shared_ids) and not sqlite_only and mismatch_count == 0,
        "sqlite_count": len(sqlite_map),
        "postgres_count": len(postgres_map),
        "shared_count": len(shared_ids),
        "shared_equal_count": len(shared_ids) - mismatch_count,
        "shared_mismatch_count": mismatch_count,
        "sqlite_only_count": len(sqlite_only),
        "postgres_only_count": len(postgres_only),
        "sqlite_only_sample": sqlite_only[:max_samples],
        "postgres_only_sample": postgres_only[:max_samples],
        "different_fields_count": dict(sorted(changed_fields.items())),
        "shared_mismatch_sample": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Local SQLite database path",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=5,
        help="Maximum difference samples",
    )
    args = parser.parse_args()

    if args.max_samples < 1:
        parser.error("--max-samples must be positive")

    if not os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL nao configurada.")

    sqlite_path = Path(args.db)
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite nao encontrado: {sqlite_path}")

    print("CP5 PostgreSQL/SQLite overlap parity (read-only)")
    print(f"SQLite: {sqlite_path}")
    print("Carregando catalogo local...")
    with SQLiteOpportunityRepository(sqlite_path) as sqlite_repo:
        sqlite_jobs = sqlite_repo.load_opportunities(active_only=False)

    print("Carregando catalogo PostgreSQL...")
    with PostgresOpportunityRepository() as postgres_repo:
        postgres_jobs = postgres_repo.load_opportunities(active_only=False)

    report = compare_overlap(
        sqlite_jobs,
        postgres_jobs,
        max_samples=args.max_samples,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["ok"]:
        print("CP5 OVERLAP PARITY: OK (extras PostgreSQL permitidos).")
    else:
        print("CP5 OVERLAP PARITY: DIFERENCAS PARA ANALISAR.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
