"""PostgreSQL read-side repository introduced in CP5-A.

Writes and lifecycle reconciliation remain on SQLite until CP5-C. This module
exists so catalog parity can be measured before the backend cutover.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from models.job import Job


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresOpportunityRepository:
    """Read the CP4 catalog model from PostgreSQL/PostGIS."""

    supports_writes = False

    def __init__(self, dsn: str | None = None):
        self.dsn = (dsn or os.getenv("DATABASE_URL", "")).strip()
        if not self.dsn:
            raise ValueError("DATABASE_URL não configurada.")
        self.conn = psycopg.connect(self.dsn, row_factory=dict_row)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()

    def count_postings(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM public.source_postings"
        ).fetchone()
        return int(row["n"])

    def known_posting_ids(
        self,
        source: str,
        *,
        prefix: str | None = None,
    ) -> set[str]:
        sql = "SELECT source_job_id FROM public.source_postings WHERE source = %s"
        args: list[Any] = [source]
        if prefix is not None:
            sql += " AND source_job_id LIKE %s"
            args.append(prefix + "%")
        return {
            str(row["source_job_id"])
            for row in self.conn.execute(sql, args).fetchall()
        }

    def known_discovery_ids(
        self,
        source: str,
        *,
        prefix: str | None = None,
    ) -> set[str]:
        sql = "SELECT source_job_id FROM public.discovery_state WHERE source = %s"
        args: list[Any] = [source]
        if prefix is not None:
            sql += " AND source_job_id LIKE %s"
            args.append(prefix + "%")
        return {
            str(row["source_job_id"])
            for row in self.conn.execute(sql, args).fetchall()
        }

    def record_discoveries(
        self,
        source: str,
        source_job_ids: Iterable[str],
        *,
        scope_status: str = "catalog",
        seen_at: str | None = None,
    ) -> int:
        """Remember IDs even when they are intentionally outside the catalog."""
        now = seen_at or _utcnow()
        ids = sorted({str(value) for value in source_job_ids if str(value)})
        if not ids:
            return 0

        sql = """
            INSERT INTO public.discovery_state AS ds(
                source, source_job_id, scope_status,
                first_seen_at, last_seen_at, last_checked_at, seen_count
            )
            VALUES(%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(source, source_job_id) DO UPDATE SET
                scope_status = CASE
                    WHEN ds.scope_status = 'catalog'
                      OR excluded.scope_status = 'catalog'
                        THEN 'catalog'
                    ELSE excluded.scope_status
                END,
                last_seen_at = excluded.last_seen_at,
                last_checked_at = excluded.last_checked_at,
                seen_count = ds.seen_count + 1
        """
        rows = [
            (source, source_job_id, scope_status, now, now, now, 1)
            for source_job_id in ids
        ]
        with self.conn.cursor() as cur:
            cur.executemany(sql, rows)
        return len(ids)

    def needs_full_audit(
        self,
        source: str,
        scope_key: str,
        *,
        every_runs: int = 7,
    ) -> bool:
        """Force an occasional full scan after partial incremental runs."""
        every = max(2, int(every_runs or 7))
        row = self.conn.execute(
            """
            SELECT successful_runs, last_full_run
            FROM public.collection_scopes
            WHERE source = %s AND scope_key = %s
            """,
            (source, scope_key),
        ).fetchone()
        if row is None:
            return False

        runs = int(row["successful_runs"] or 0)
        last_full = int(row["last_full_run"] or 0)
        return (runs - last_full) >= (every - 1)

    def finish_scope_run(
        self,
        source: str,
        scope_key: str,
        *,
        coverage: str,
        finished_at: str | None = None,
    ) -> None:
        """Advance persistent collection-scope counters atomically."""
        now = finished_at or _utcnow()
        self.conn.execute(
            """
            INSERT INTO public.collection_scopes AS scopes(
                source, scope_key, successful_runs,
                last_full_run, last_coverage, last_run_at
            )
            VALUES(
                %s,
                %s,
                1,
                CASE WHEN %s = 'complete' THEN 1 ELSE 0 END,
                %s,
                %s
            )
            ON CONFLICT(source, scope_key) DO UPDATE SET
                successful_runs = scopes.successful_runs + 1,
                last_full_run = CASE
                    WHEN excluded.last_coverage = 'complete'
                        THEN scopes.successful_runs + 1
                    ELSE scopes.last_full_run
                END,
                last_coverage = excluded.last_coverage,
                last_run_at = excluded.last_run_at
            """,
            (source, scope_key, coverage, coverage, now),
        )

    def load_opportunities(self, *, active_only: bool = True) -> list[Job]:
        sql = """
            SELECT
                o.id,
                o.company,
                o.title,
                o.description,
                o.location_text,
                o.location_confidence,
                o.workplace_type,
                o.employment_type,
                o.salary,
                o.published_at,
                o.canonical_url,
                o.created_at,
                o.updated_at,
                CASE
                    WHEN o.location IS NULL THEN NULL
                    ELSE extensions.st_y(o.location::extensions.geometry)
                END AS latitude,
                CASE
                    WHEN o.location IS NULL THEN NULL
                    ELSE extensions.st_x(o.location::extensions.geometry)
                END AS longitude
            FROM public.opportunities o
        """
        if active_only:
            sql += """
                WHERE EXISTS (
                    SELECT 1
                    FROM public.source_postings p
                    WHERE p.opportunity_id = o.id
                      AND p.is_active = true
                )
            """
        sql += " ORDER BY o.created_at, o.id"

        opportunities = self.conn.execute(sql).fetchall()
        if not opportunities:
            return []

        ids = [row["id"] for row in opportunities]

        postings_by_opportunity = {value: [] for value in ids}
        for row in self.conn.execute(
            """
            SELECT *
            FROM public.source_postings
            WHERE opportunity_id = ANY(%s)
            ORDER BY opportunity_id, first_seen_at, source, source_job_id
            """,
            (ids,),
        ).fetchall():
            postings_by_opportunity[row["opportunity_id"]].append(row)

        scores_by_opportunity = {value: {} for value in ids}
        for row in self.conn.execute(
            """
            SELECT opportunity_id, course_id, score
            FROM public.opportunity_course_scores
            WHERE opportunity_id = ANY(%s)
            ORDER BY opportunity_id, course_id
            """,
            (ids,),
        ).fetchall():
            scores_by_opportunity[row["opportunity_id"]][
                str(row["course_id"])
            ] = int(row["score"])

        intents_by_opportunity = {value: [] for value in ids}
        for row in self.conn.execute(
            """
            SELECT opportunity_id, intent_id
            FROM public.opportunity_intents
            WHERE opportunity_id = ANY(%s)
            ORDER BY opportunity_id, intent_id
            """,
            (ids,),
        ).fetchall():
            intents_by_opportunity[row["opportunity_id"]].append(
                str(row["intent_id"])
            )

        jobs: list[Job] = []
        for row in opportunities:
            opportunity_id = row["id"]
            postings = postings_by_opportunity.get(opportunity_id, [])
            if not postings:
                continue

            representative = postings[0]
            references = [
                {
                    "source": str(posting["source"]),
                    "source_job_id": str(posting["source_job_id"]),
                    "url": str(posting["url"] or ""),
                }
                for posting in postings
            ]
            metadata = {
                "opportunity_id": str(opportunity_id),
                "classification_source": "relational",
                "catalog_source": "postgres_opportunities",
                "source_posting_count": len(postings),
                "source_references": references,
                "opportunity_is_active": any(
                    bool(posting["is_active"]) for posting in postings
                ),
            }

            jobs.append(
                Job(
                    source=str(representative["source"]),
                    source_job_id=str(representative["source_job_id"]),
                    company=str(row["company"] or ""),
                    title=str(row["title"] or ""),
                    location=str(row["location_text"] or ""),
                    url=str(representative["url"] or row["canonical_url"] or ""),
                    description=str(row["description"] or ""),
                    published_at=_iso(row["published_at"]),
                    employment_type=row["employment_type"],
                    workplace_type=row["workplace_type"],
                    source_type=str(
                        representative["source_type"] or "official_api"
                    ),
                    salary=row["salary"],
                    latitude=(
                        float(row["latitude"])
                        if row["latitude"] is not None
                        else None
                    ),
                    longitude=(
                        float(row["longitude"])
                        if row["longitude"] is not None
                        else None
                    ),
                    location_confidence=row["location_confidence"],
                    detected_intents=list(
                        intents_by_opportunity.get(opportunity_id, [])
                    ),
                    course_scores=dict(
                        scores_by_opportunity.get(opportunity_id, {})
                    ),
                    metadata=metadata,
                )
            )
        return jobs

    def nearby_opportunities(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_meters: float = 50_000,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM public.nearby_opportunities(%s, %s, %s, %s)
            """,
            (latitude, longitude, radius_meters, max_results),
        ).fetchall()
        return [dict(row) for row in rows]

    def lifecycle_stats(self) -> dict[str, int]:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE is_active AND miss_count = 0) AS active,
                COUNT(*) FILTER (WHERE is_active AND miss_count > 0) AS missing,
                COUNT(*) FILTER (WHERE NOT is_active) AS inactive
            FROM public.source_postings
            """
        ).fetchone()
        discovery = self.conn.execute(
            """
            SELECT
                COUNT(*) AS discoveries,
                COUNT(*) FILTER (WHERE scope_status = 'out_of_scope')
                    AS out_of_scope
            FROM public.discovery_state
            """
        ).fetchone()
        return {
            "active": int(row["active"] or 0),
            "missing": int(row["missing"] or 0),
            "inactive": int(row["inactive"] or 0),
            "discoveries": int(discovery["discoveries"] or 0),
            "out_of_scope_discoveries": int(discovery["out_of_scope"] or 0),
        }

    def stats(self) -> dict[str, Any]:
        counts = {}
        for table in (
            "opportunities",
            "source_postings",
            "opportunity_course_scores",
            "opportunity_intents",
            "discovery_state",
            "collection_scopes",
        ):
            row = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM public.{table}"
            ).fetchone()
            counts[table] = int(row["n"])
        return {
            "repository": "postgres",
            **counts,
            "lifecycle": self.lifecycle_stats(),
        }
