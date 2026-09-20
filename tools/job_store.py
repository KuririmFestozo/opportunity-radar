"""Inspect the local Opportunity Radar incremental SQLite store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.job_store import DEFAULT_DB_PATH, JobStore


def main():
    parser = argparse.ArgumentParser(
        description="Opportunity Radar incremental job store"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument(
        "--bootstrap",
        metavar="JOBS_JSON",
        help="Seed an empty database from an existing jobs.json",
    )
    args = parser.parse_args()

    with JobStore(Path(args.db)) as store:
        if args.bootstrap:
            result = store.bootstrap_from_json(args.bootstrap)
            print(f"Bootstrap: {result['imported']} vagas importadas")

        stats = store.stats()
        print("Opportunity Radar — Incremental Job Store")
        print(f"Banco:  {stats['path']}")
        print(f"Total:  {stats['total_jobs']}")
        print(f"Ativas: {stats['active_jobs']}")
        print(f"Versão: {stats['processing_version']}")
        if stats["by_source"]:
            print("\nPor fonte:")
            for source, count in stats["by_source"].items():
                print(f"  {source:<22} {count:>6}")


if __name__ == "__main__":
    main()
