"""PostgreSQL read-side repository introduced in CP5-A.

Writes and lifecycle reconciliation remain on SQLite until CP5-C. This module
exists so catalog parity can be measured before the backend cutover.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from models.job import Job


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


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
