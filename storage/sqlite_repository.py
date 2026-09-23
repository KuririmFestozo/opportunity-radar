"""SQLite implementation of the Opportunity Radar repository contract."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from models.job import Job
from storage.incremental_state import (
    ensure_incremental_schema,
    finish_scope_run as _finish_scope_run,
    known_discovery_ids as _known_discovery_ids,
    lifecycle_stats as _lifecycle_stats,
    mark_seen_ids as _mark_seen_ids,
    mark_seen_jobs as _mark_seen_jobs,
    needs_full_audit as _needs_full_audit,
    reconcile_scope as _reconcile_scope,
    record_discoveries as _record_discoveries,
)
from storage.job_store import DEFAULT_DB_PATH, PROCESSING_VERSION, JobStore
from storage.unified_schema import (
    sync_unified_persistence,
    unified_schema_stats,
)


class SQLiteOpportunityRepository:
    """Composition wrapper around the legacy JobStore during CP4.

    ``JobStore`` remains available for compatibility tests/tools, but the main
    collection pipeline should depend on this repository instead.
    """

    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self._store = JobStore(path)
        ensure_incremental_schema(self._store)

    @property
    def path(self) -> Path:
        return self._store.path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        self._store.close()

    def commit(self) -> None:
        self._store.commit()

    def bootstrap_from_json(self, path: str | Path) -> dict:
        return self._store.bootstrap_from_json(path)

    def count_postings(self) -> int:
        return self._store.count()

    def known_posting_ids(
        self,
        source: str,
        *,
        prefix: str | None = None,
    ) -> set[str]:
        return self._store.known_ids(source, prefix=prefix)

    def prepare_posting(self, incoming: Job) -> tuple[Job, str, bool]:
        return self._store.prepare(incoming)

    def upsert_posting(
        self,
        job: Job,
        *,
        seen_at: str | None = None,
        processing_version: str | None = None,
        commit: bool = False,
    ) -> None:
        self._store.upsert(
            job,
            seen_at=seen_at,
            processing_version=processing_version or PROCESSING_VERSION,
            commit=commit,
        )

    def touch_posting(
        self,
        source: str,
        source_job_id: str,
        *,
        seen_at: str | None = None,
        commit: bool = False,
    ) -> None:
        self._store.touch(
            source,
            source_job_id,
            seen_at=seen_at,
            commit=commit,
        )

    def load_postings(self, *, active_only: bool = True) -> list[Job]:
        jobs = self._store.load_jobs(active_only=active_only)
        if not jobs:
            return jobs

        required = {
            "source_postings",
            "opportunity_course_scores",
            "opportunity_intents",
        }
        present = {
            str(row[0])
            for row in self._store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if not required <= present:
            return jobs

        keys = {(job.source, job.source_job_id) for job in jobs}
        opportunity_by_posting = {
            (str(row["source"]), str(row["source_job_id"])): str(
                row["opportunity_id"]
            )
            for row in self._store.conn.execute(
                """
                SELECT source, source_job_id, opportunity_id
                FROM source_postings
                """
            ).fetchall()
            if (str(row["source"]), str(row["source_job_id"])) in keys
        }

        opportunity_ids = set(opportunity_by_posting.values())
        if not opportunity_ids:
            return jobs

        scores_by_opportunity = {
            opportunity_id: {} for opportunity_id in opportunity_ids
        }
        for row in self._store.conn.execute(
            """
            SELECT opportunity_id, course_id, score
            FROM opportunity_course_scores
            """
        ).fetchall():
            opportunity_id = str(row["opportunity_id"])
            if opportunity_id in scores_by_opportunity:
                scores_by_opportunity[opportunity_id][
                    str(row["course_id"])
                ] = int(row["score"])

        intents_by_opportunity = {
            opportunity_id: [] for opportunity_id in opportunity_ids
        }
        for row in self._store.conn.execute(
            """
            SELECT opportunity_id, intent_id
            FROM opportunity_intents
            ORDER BY opportunity_id, intent_id
            """
        ).fetchall():
            opportunity_id = str(row["opportunity_id"])
            if opportunity_id in intents_by_opportunity:
                intents_by_opportunity[opportunity_id].append(
                    str(row["intent_id"])
                )

        for job in jobs:
            opportunity_id = opportunity_by_posting.get(
                (job.source, job.source_job_id)
            )
            if opportunity_id is None:
                continue
            job.course_scores = dict(
                scores_by_opportunity.get(opportunity_id, {})
            )
            job.detected_intents = list(
                intents_by_opportunity.get(opportunity_id, [])
            )
            metadata = dict(job.metadata or {})
            metadata["opportunity_id"] = opportunity_id
            metadata["classification_source"] = "relational"
            job.metadata = metadata

        return jobs

    def load_opportunities(self, *, active_only: bool = True) -> list[Job]:
        """Load the user-facing catalog directly from relational opportunities."""
        conn = self._store.conn

        required = {
            "opportunities",
            "source_postings",
            "opportunity_course_scores",
            "opportunity_intents",
        }
        present = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if not required <= present:
            return []

        sql = """
            SELECT *
            FROM opportunities o
        """
        if active_only:
            sql += """
            WHERE EXISTS (
                SELECT 1
                FROM source_postings p
                WHERE p.opportunity_id = o.id
                  AND p.is_active = 1
            )
            """
        sql += " ORDER BY o.created_at, o.id"

        opportunity_rows = conn.execute(sql).fetchall()
        if not opportunity_rows:
            return []

        opportunity_ids = {str(row["id"]) for row in opportunity_rows}

        postings_by_opportunity = {
            opportunity_id: [] for opportunity_id in opportunity_ids
        }
        for row in conn.execute(
            """
            SELECT *
            FROM source_postings
            ORDER BY opportunity_id, first_seen_at, source, source_job_id
            """
        ).fetchall():
            opportunity_id = str(row["opportunity_id"])
            if opportunity_id in postings_by_opportunity:
                postings_by_opportunity[opportunity_id].append(row)

        scores_by_opportunity = {
            opportunity_id: {} for opportunity_id in opportunity_ids
        }
        for row in conn.execute(
            """
            SELECT opportunity_id, course_id, score
            FROM opportunity_course_scores
            ORDER BY opportunity_id, course_id
            """
        ).fetchall():
            opportunity_id = str(row["opportunity_id"])
            if opportunity_id in scores_by_opportunity:
                scores_by_opportunity[opportunity_id][str(row["course_id"])] = int(
                    row["score"]
                )

        intents_by_opportunity = {
            opportunity_id: [] for opportunity_id in opportunity_ids
        }
        for row in conn.execute(
            """
            SELECT opportunity_id, intent_id
            FROM opportunity_intents
            ORDER BY opportunity_id, intent_id
            """
        ).fetchall():
            opportunity_id = str(row["opportunity_id"])
            if opportunity_id in intents_by_opportunity:
                intents_by_opportunity[opportunity_id].append(
                    str(row["intent_id"])
                )

        jobs = []
        for row in opportunity_rows:
            opportunity_id = str(row["id"])
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
                "opportunity_id": opportunity_id,
                "classification_source": "relational",
                "catalog_source": "relational_opportunities",
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
                    url=str(
                        representative["url"]
                        or row["canonical_url"]
                        or ""
                    ),
                    description=str(row["description"] or ""),
                    published_at=row["published_at"],
                    employment_type=row["employment_type"],
                    workplace_type=row["workplace_type"],
                    source_type=str(
                        representative["source_type"] or "official_api"
                    ),
                    salary=row["salary"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
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

    def known_discovery_ids(
        self,
        source: str,
        *,
        prefix: str | None = None,
    ) -> set[str]:
        return _known_discovery_ids(self._store, source, prefix=prefix)

    def record_discoveries(
        self,
        source: str,
        source_job_ids: Iterable[str],
        *,
        scope_status: str = "catalog",
        seen_at: str | None = None,
    ) -> int:
        return _record_discoveries(
            self._store,
            source,
            source_job_ids,
            scope_status=scope_status,
            seen_at=seen_at,
        )

    def mark_seen_ids(
        self,
        source: str,
        source_job_ids: Iterable[str],
        *,
        scope_status: str = "catalog",
        seen_at: str | None = None,
    ) -> dict:
        return _mark_seen_ids(
            self._store,
            source,
            source_job_ids,
            scope_status=scope_status,
            seen_at=seen_at,
        )

    def mark_seen_postings(
        self,
        jobs: Iterable[Job],
        *,
        seen_at: str | None = None,
    ) -> dict:
        return _mark_seen_jobs(
            self._store,
            jobs,
            seen_at=seen_at,
        )

    def reconcile_scope(
        self,
        source: str,
        seen_source_job_ids: Iterable[str],
        *,
        prefix: str | None = None,
        coverage: str = "partial",
        miss_threshold: int = 2,
        checked_at: str | None = None,
    ) -> dict:
        return _reconcile_scope(
            self._store,
            source,
            seen_source_job_ids,
            prefix=prefix,
            coverage=coverage,
            miss_threshold=miss_threshold,
            checked_at=checked_at,
        )

    def needs_full_audit(
        self,
        source: str,
        scope_key: str,
        *,
        every_runs: int = 7,
    ) -> bool:
        return _needs_full_audit(
            self._store,
            source,
            scope_key,
            every_runs=every_runs,
        )

    def finish_scope_run(
        self,
        source: str,
        scope_key: str,
        *,
        coverage: str,
        finished_at: str | None = None,
    ) -> None:
        _finish_scope_run(
            self._store,
            source,
            scope_key,
            coverage=coverage,
            finished_at=finished_at,
        )

    def lifecycle_stats(self) -> dict:
        return _lifecycle_stats(self._store)

    def sync_unified_schema(self) -> dict:
        return sync_unified_persistence(self._store)

    def stats(self) -> dict:
        legacy = self._store.stats()
        unified = unified_schema_stats(self._store)
        return {
            **legacy,
            "repository": "sqlite",
            "unified": unified,
        }
