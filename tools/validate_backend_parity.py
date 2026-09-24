"""Validate CP5-B read parity between SQLite and PostgreSQL.

This command is read-only. It compares the user-facing catalog produced by the
two repository implementations and performs a PostGIS proximity smoke test.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.job import Job
from storage.job_store import DEFAULT_DB_PATH
from storage.postgres_repository import PostgresOpportunityRepository
from storage.sqlite_repository import SQLiteOpportunityRepository


def _norm_time(value: Any) -> str:
    if value in (None, ""):
        return ""
    raw = value.isoformat() if hasattr(value, "isoformat") else str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat()


def _norm_float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 7)


def _source_refs(job: Job) -> tuple[tuple[str, str, str], ...]:
    refs = (job.metadata or {}).get("source_references") or []
    normalized = {
        (
            str(ref.get("source") or ""),
            str(ref.get("source_job_id") or ""),
            str(ref.get("url") or ""),
        )
        for ref in refs
        if isinstance(ref, dict)
    }
    return tuple(sorted(normalized))


def job_signature(job: Job) -> dict[str, Any]:
    """Comparable catalog representation, excluding backend-only metadata."""
    return {
        "source": str(job.source or ""),
        "source_job_id": str(job.source_job_id or ""),
        "company": str(job.company or ""),
        "title": str(job.title or ""),
        "location": str(job.location or ""),
        "url": str(job.url or ""),
        "description": str(job.description or ""),
        "published_at": _norm_time(job.published_at),
        "employment_type": job.employment_type,
        "workplace_type": job.workplace_type,
        "source_type": str(job.source_type or ""),
        "salary": job.salary,
        "latitude": _norm_float(job.latitude),
        "longitude": _norm_float(job.longitude),
        "location_confidence": job.location_confidence,
        "detected_intents": tuple(sorted(str(v) for v in job.detected_intents)),
        "course_scores": tuple(
            sorted((str(k), int(v)) for k, v in job.course_scores.items())
        ),
        "source_references": _source_refs(job),
        "opportunity_is_active": bool(
            (job.metadata or {}).get("opportunity_is_active")
        ),
    }


def _by_opportunity_id(jobs: list[Job]) -> dict[str, Job]:
    result: dict[str, Job] = {}
    for job in jobs:
        opportunity_id = str((job.metadata or {}).get("opportunity_id") or "")
        if not opportunity_id:
            raise RuntimeError(
                "Repository returned a catalog job without opportunity_id: "
                f"{job.source}:{job.source_job_id}"
            )
        if opportunity_id in result:
            raise RuntimeError(f"Duplicate opportunity_id: {opportunity_id}")
        result[opportunity_id] = job
    return result


def compare_catalogs(
    sqlite_jobs: list[Job],
    postgres_jobs: list[Job],
    *,
    max_mismatches: int = 10,
) -> dict[str, Any]:
    sqlite_by_id = _by_opportunity_id(sqlite_jobs)
    postgres_by_id = _by_opportunity_id(postgres_jobs)

    sqlite_ids = set(sqlite_by_id)
    postgres_ids = set(postgres_by_id)
    only_sqlite = sorted(sqlite_ids - postgres_ids)
    only_postgres = sorted(postgres_ids - sqlite_ids)

    mismatches: list[dict[str, Any]] = []
    mismatch_count = 0
    for opportunity_id in sorted(sqlite_ids & postgres_ids):
        left = job_signature(sqlite_by_id[opportunity_id])
        right = job_signature(postgres_by_id[opportunity_id])
        if left == right:
            continue

        mismatch_count += 1
        if len(mismatches) >= max_mismatches:
            continue
        fields = {
            key: {"sqlite": left[key], "postgres": right[key]}
            for key in left
            if left[key] != right[key]
        }
        mismatches.append(
            {
                "opportunity_id": opportunity_id,
                "fields": fields,
            }
        )

    return {
        "ok": (
            not only_sqlite
            and not only_postgres
            and mismatch_count == 0
        ),
        "sqlite_count": len(sqlite_by_id),
        "postgres_count": len(postgres_by_id),
        "only_sqlite_count": len(only_sqlite),
        "only_postgres_count": len(only_postgres),
        "only_sqlite_sample": only_sqlite[:max_mismatches],
        "only_postgres_sample": only_postgres[:max_mismatches],
        "mismatch_count": mismatch_count,
        "mismatch_sample": mismatches,
    }


def _postgis_smoke(repo: PostgresOpportunityRepository, jobs: list[Job]) -> dict:
    sample = next(
        (
            job
            for job in jobs
            if job.latitude is not None and job.longitude is not None
        ),
        None,
    )
    if sample is None:
        return {"ok": False, "reason": "no_geocoded_opportunities"}

    rows = repo.nearby_opportunities(
        latitude=float(sample.latitude),
        longitude=float(sample.longitude),
        radius_meters=100,
        max_results=100,
    )
    if not rows:
        return {"ok": False, "reason": "postgis_returned_no_rows"}

    distances = [
        float(row["dist_meters"])
        for row in rows
        if row.get("dist_meters") is not None
    ]
    return {
        "ok": bool(distances) and min(distances) <= 1.0,
        "rows": len(rows),
        "minimum_distance_meters": min(distances) if distances else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate SQLite/PostgreSQL catalog read parity."
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
        "--max-mismatches",
        type=int,
        default=10,
        help="Maximum mismatch details to print.",
    )
    args = parser.parse_args()

    dsn = str(args.database_url or "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL não configurada.")

    sqlite_path = Path(args.db)
    print("CP5-B backend read parity")
    print(f"SQLite: {sqlite_path}")
    print("Carregando catálogo SQLite...")
    with SQLiteOpportunityRepository(sqlite_path) as sqlite_repo:
        sqlite_jobs = sqlite_repo.load_opportunities(active_only=False)
        sqlite_lifecycle = sqlite_repo.lifecycle_stats()

    print(f"SQLite catalog: {len(sqlite_jobs)} opportunities")
    print("Carregando catálogo PostgreSQL...")
    with PostgresOpportunityRepository(dsn) as postgres_repo:
        postgres_jobs = postgres_repo.load_opportunities(active_only=False)
        postgres_lifecycle = postgres_repo.lifecycle_stats()
        postgis = _postgis_smoke(postgres_repo, postgres_jobs)

    print(f"PostgreSQL catalog: {len(postgres_jobs)} opportunities")
    print("Comparando IDs, campos, classificação e source references...")
    result = compare_catalogs(
        sqlite_jobs,
        postgres_jobs,
        max_mismatches=max(1, args.max_mismatches),
    )

    print(
        "IDs exclusivos: "
        f"SQLite={result['only_sqlite_count']} "
        f"PostgreSQL={result['only_postgres_count']}"
    )
    print(f"Opportunities divergentes: {result['mismatch_count']}")
    print(f"Lifecycle SQLite: {sqlite_lifecycle}")
    print(f"Lifecycle PostgreSQL: {postgres_lifecycle}")
    print(f"PostGIS smoke: {postgis}")

    if result["only_sqlite_sample"]:
        print(f"Somente SQLite: {result['only_sqlite_sample']}")
    if result["only_postgres_sample"]:
        print(f"Somente PostgreSQL: {result['only_postgres_sample']}")
    for mismatch in result["mismatch_sample"]:
        print(
            f"Mismatch {mismatch['opportunity_id']}: "
            f"{mismatch['fields']}"
        )

    lifecycle_ok = sqlite_lifecycle == postgres_lifecycle
    postgis_ok = bool(postgis.get("ok"))
    if not result["ok"] or not lifecycle_ok or not postgis_ok:
        print("CP5-B parity: FAILED")
        raise SystemExit(1)

    print("CP5-B parity: OK")


if __name__ == "__main__":
    main()
