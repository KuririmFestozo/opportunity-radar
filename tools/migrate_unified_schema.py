"""Migrate/validate the local Opportunity Radar SQLite database to CP4-A."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.job_store import DEFAULT_DB_PATH, JobStore
from storage.unified_schema import (
    sync_unified_persistence,
    validate_unified_schema,
)

import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create and validate the CP4-A unified shadow schema."
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path (default: data/opportunity_radar.db)",
    )
    args = parser.parse_args()

    path = Path(args.db)
    with JobStore(path) as store:
        result = sync_unified_persistence(store)
        validation = validate_unified_schema(store, require_tables=True)

    print("CP4 unified persistence")
    print(f"Database: {path}")
    print(f"Legacy jobs scanned: {result['legacy_jobs_scanned']}")
    print(f"Opportunities: {result['opportunities']}")
    print(f"Source postings: {result['source_postings']}")
    print(f"Active opportunities: {result['active_opportunities']}")
    print(f"Cross-source opportunities: {result['cross_source_opportunities']}")
    print(f"Course scores: {result['course_scores']}")
    print(f"Intents: {result['intents']}")
    print(f"Schema version: {result['schema_version']}")
    print(f"Shadow mode: {result['shadow_mode']}")
    print(f"Posting rows synced: {result.get('posting_rows_synced', 0)}")
    print(f"Association changes: {result.get('association_changes', 0)}")
    print(f"Opportunities rebuilt: {result.get('opportunities_rebuilt', 0)}")
    print(f"Validation: {'OK' if validation['ok'] else 'FAILED'}")

    if not validation["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
