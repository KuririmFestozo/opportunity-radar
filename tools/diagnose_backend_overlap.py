"""Diagnose SQLite/PostgreSQL snapshot drift without changing either DB.

Requires DATABASE_URL. Run after validate_backend_overlap:
    python -m tools.diagnose_backend_overlap

This compares source hashes and processing versions only for opportunities
that have different user-facing fields across the two snapshots. No writes.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from models.job import Job
from storage.job_store import DEFAULT_DB_PATH
from storage.postgres_repository import PostgresOpportunityRepository
from storage.sqlite_repository import SQLiteOpportunityRepository
from tools.validate_backend_parity import _by_opportunity_id, job_signature


_POSTINGS_SQL = """
    SELECT opportunity_id, source, source_job_id,
           raw_hash, processing_version, last_changed_at
    FROM source_postings
"""


def _posting_map(rows: Iterable[Any]) -> dict[str, dict[tuple[str, str], dict]]:
    grouped: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)
    for row in rows:
        opportunity_id = str(row["opportunity_id"])
        key = (str(row["source"]), str(row["source_job_id"]))
        grouped[opportunity_id][key] = {
            "raw_hash": str(row["raw_hash"] or ""),
            "processing_version": str(row["processing_version"] or ""),
            "last_changed_at": row["last_changed_at"],
        }
    return grouped


def _to_timestamp(raw: Any) -> datetime | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = raw if isinstance(raw, datetime) else datetime.fromisoformat(
            str(raw).replace("Z", "+00:00")
        )
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except ValueError:
        return None


def diagnose(
    sqlite_jobs: list[Job],
    postgres_jobs: list[Job],
    sqlite_posting_rows: Iterable[Any],
    postgres_posting_rows: Iterable[Any],
    *,
    max_samples: int = 5,
) -> dict[str, Any]:
    if max_samples < 1:
        raise ValueError("max_samples deve ser >= 1")

    left = _by_opportunity_id(sqlite_jobs)
    right = _by_opportunity_id(postgres_jobs)
    sqlite_postings = _posting_map(sqlite_posting_rows)
    postgres_postings = _posting_map(postgres_posting_rows)
    shared = set(left) & set(right)
    category_count: Counter[str] = Counter()
    field_count: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    mismatches = 0

    for opportunity_id in sorted(shared):
        old = job_signature(left[opportunity_id])
        new = job_signature(right[opportunity_id])
        fields = sorted(k for k in old if old[k] != new[k])
        if not fields:
            continue
        mismatches += 1
        field_count.update(fields)

        before = sqlite_postings.get(opportunity_id, {})
        after = postgres_postings.get(opportunity_id, {})
        by_source.update({key[0] for key in before} | {key[0] for key in after})
        common_keys = set(before) & set(after)
        hash_changed = any(
            before[key]["raw_hash"] != after[key]["raw_hash"]
            for key in common_keys
        )
        version_changed = any(
            before[key]["processing_version"]
            != after[key]["processing_version"]
            for key in common_keys
        )
        newer = any(
            _to_timestamp(after[key]["last_changed_at"]) is not None
            and _to_timestamp(before[key]["last_changed_at"]) is not None
            and _to_timestamp(after[key]["last_changed_at"])
            > _to_timestamp(before[key]["last_changed_at"])
            for key in common_keys
        )
        same_keys = bool(before) and set(before) == set(after)

        if fields == ["course_scores"]:
            category_count["course_scores_only"] += 1
        if "course_scores" in fields:
            category_count["course_scores_changed"] += 1
            before_scores = dict(old["course_scores"])
            after_scores = dict(new["course_scores"])
            if any(v > 0 for v in before_scores.values()) and not any(
                v > 0 for v in after_scores.values()
            ):
                category_count["scores_positive_sqlite_zero_postgres"] += 1
            if any(v > 0 for v in after_scores.values()) and not any(
                v > 0 for v in before_scores.values()
            ):
                category_count["scores_zero_sqlite_positive_postgres"] += 1

        if not same_keys:
            category_count["source_posting_set_changed_or_missing"] += 1
        if hash_changed:
            category_count["raw_hash_changed"] += 1
        if version_changed:
            category_count["processing_version_changed"] += 1
        if newer:
            category_count["postgres_last_changed_newer"] += 1
        if same_keys and not hash_changed and not version_changed:
            category_count["same_sources_hash_and_version"] += 1

        if len(samples) < max_samples:
            samples.append({
                "opportunity_id": opportunity_id,
                "fields": fields,
                "sources_in_both": sorted({s for s, _ in common_keys}),
                "source_set_equal": same_keys,
                "raw_hash_changed": hash_changed,
                "processing_version_changed": version_changed,
                "postgres_last_changed_newer": newer,
            })

    return {
        "shared_opportunities": len(shared),
        "mismatched_opportunities": mismatches,
        "changed_fields": dict(sorted(field_count.items())),
        "diagnostic_counts": dict(sorted(category_count.items())),
        "mismatches_by_source": dict(sorted(by_source.items())),
        "sample": samples,
        "read_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--max-samples", type=int, default=5)
    args = parser.parse_args()
    if args.max_samples < 1:
        parser.error("--max-samples deve ser >= 1")
    if not os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL nao configurada.")

    db = Path(args.db)
    if not db.is_file():
        raise SystemExit(f"SQLite nao encontrado: {db}")

    print("CP5 snapshot drift diagnostic (read-only)")
    with SQLiteOpportunityRepository(db) as repo:
        sqlite_jobs = repo.load_opportunities(active_only=False)
        sqlite_postings = repo._store.conn.execute(_POSTINGS_SQL).fetchall()

    with PostgresOpportunityRepository() as repo:
        postgres_jobs = repo.load_opportunities(active_only=False)
        postgres_postings = repo.conn.execute(
            _POSTINGS_SQL.replace("FROM source_postings", "FROM public.source_postings")
        ).fetchall()

    result = diagnose(
        sqlite_jobs, postgres_jobs,
        sqlite_postings, postgres_postings,
        max_samples=args.max_samples,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("DIAGNOSTICO CONCLUIDO: nenhum banco foi modificado.")


if __name__ == "__main__":
    main()
