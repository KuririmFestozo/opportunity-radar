"""PostgreSQL/PostGIS repository for the CP5 persistence backend.

The repository writes source-native postings directly and reconciles the
user-facing opportunity catalog with the same conservative cross-source URL
identity rules used by the SQLite CP4 implementation.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from models.job import Job
from processing.deduplicate import (
    canonical_job_url,
    deduplicate_job_groups,
    deduplicate_jobs,
)
from storage.job_store import (
    PROCESSING_VERSION,
    _clean_metadata,
    _job_from_dict,
    _merge_cached_fields,
    raw_content_hash,
)
from storage.unified_schema import (
    _course_scores,
    _intents,
    _stable_opportunity_id,
)


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()



def _association_plan(
    rows: Iterable[dict[str, Any]],
    *,
    dirty_keys: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Compute conservative desired associations without mutating PostgreSQL."""
    rows = list(rows)
    jobs: list[Job] = []
    times: dict[tuple[str, str], tuple[Any, Any]] = {}
    current_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        key = (str(row["source"]), str(row["source_job_id"]))
        payload = dict(row["normalized_job_json"] or {})
        job = _job_from_dict(payload)
        job.source, job.source_job_id = key
        jobs.append(job)
        times[key] = (row["first_seen_at"], row["last_changed_at"])
        current_by_key[key] = row

    groups = deduplicate_job_groups(jobs)
    desired_by_key: dict[tuple[str, str], tuple[str, str]] = {}
    groups_by_opportunity: dict[str, list[Job]] = {}

    for group in groups:
        if not group:
            continue
        anchor = min(
            group,
            key=lambda job: (
                times[(job.source, job.source_job_id)][0],
                job.source,
                job.source_job_id,
            ),
        )
        opportunity_id = _stable_opportunity_id(
            anchor.source,
            anchor.source_job_id,
        )
        method = "conservative_url" if len(group) > 1 else "identity"
        groups_by_opportunity[opportunity_id] = group
        for job in group:
            desired_by_key[(job.source, job.source_job_id)] = (
                opportunity_id,
                method,
            )

    link_updates: list[tuple[str, str, str, str]] = []
    affected_opportunity_ids: set[str] = set()

    for key, (desired_id, desired_method) in desired_by_key.items():
        current = current_by_key[key]
        current_id = str(current["opportunity_id"])
        current_method = str(current.get("association_method") or "identity")
        if current_id != desired_id or current_method != desired_method:
            affected_opportunity_ids.update((current_id, desired_id))
            link_updates.append(
                (desired_id, desired_method, key[0], key[1])
            )

    for key in dirty_keys or set():
        desired = desired_by_key.get(key)
        if desired is not None:
            affected_opportunity_ids.add(desired[0])

    # Cross-source groups are expected to stay sparse. Rebuilding all of them
    # also repairs a prior interrupted reconciliation if in-memory dirty state
    # was lost between processes.
    for opportunity_id, group in groups_by_opportunity.items():
        if len(group) > 1:
            affected_opportunity_ids.add(opportunity_id)

    return {
        "groups": groups,
        "groups_by_opportunity": groups_by_opportunity,
        "desired_by_key": desired_by_key,
        "times": times,
        "link_updates": link_updates,
        "affected_opportunity_ids": affected_opportunity_ids,
    }


def _normalized_payload(job: Job) -> dict[str, Any]:
    payload = job.to_dict()
    payload["metadata"] = _clean_metadata(payload.get("metadata"))
    return json.loads(
        json.dumps(payload, ensure_ascii=False, default=str)
    )


class PostgresOpportunityRepository:
    """Read the CP4 catalog model from PostgreSQL/PostGIS."""

    supports_writes = True

    def __init__(self, dsn: str | None = None):
        self.dsn = (dsn or os.getenv("DATABASE_URL", "")).strip()
        if not self.dsn:
            raise ValueError("DATABASE_URL não configurada.")
        self.conn = psycopg.connect(self.dsn, row_factory=dict_row)
        self._association_dirty_keys: set[tuple[str, str]] = set()

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

    def prepare_posting(self, incoming: Job) -> tuple[Job, str, bool]:
        """Return the cached/merged posting state and whether it needs processing."""
        row = self.conn.execute(
            """
            SELECT normalized_job_json, raw_hash, processing_version
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (incoming.source, incoming.source_job_id),
        ).fetchone()

        if row is None:
            return incoming, "new", True

        payload = dict(row["normalized_job_json"] or {})
        cached = _job_from_dict(payload)
        candidate = _merge_cached_fields(incoming, cached)
        same_raw = raw_content_hash(candidate) == str(row["raw_hash"])

        if same_raw and str(row["processing_version"]) == PROCESSING_VERSION:
            references = (candidate.metadata or {}).get("source_references")
            cached_references = (cached.metadata or {}).get("source_references")
            if references != cached_references:
                cached.metadata["source_references"] = references
                refreshed = _normalized_payload(cached)
                self.conn.execute(
                    """
                    UPDATE public.source_postings
                    SET normalized_job_json = %s
                    WHERE source = %s AND source_job_id = %s
                    """,
                    (Jsonb(refreshed), cached.source, cached.source_job_id),
                )
            return cached, "unchanged", False

        if same_raw:
            return candidate, "reprocess", True

        return candidate, "changed", True

    def _upsert_posting_core(
        self,
        job: Job,
        *,
        seen_at: str | None = None,
        processing_version: str | None = None,
    ) -> str:
        """Persist opportunity + source posting identity, excluding scores/intents."""
        now = seen_at or _utcnow()
        version = processing_version or PROCESSING_VERSION
        new_hash = raw_content_hash(job)

        current = self.conn.execute(
            """
            SELECT opportunity_id, first_seen_at, last_changed_at, raw_hash
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (job.source, job.source_job_id),
        ).fetchone()

        if current is None:
            opportunity_id = _stable_opportunity_id(
                job.source,
                job.source_job_id,
            )
            first_seen = now
            last_changed = now
        else:
            opportunity_id = str(current["opportunity_id"])
            first_seen = current["first_seen_at"]
            last_changed = (
                current["last_changed_at"]
                if str(current["raw_hash"]) == new_hash
                else now
            )

        payload = _normalized_payload(job)
        canonical = canonical_job_url(job.url) or job.url or None

        self.conn.execute(
            """
            INSERT INTO public.opportunities(
                id, company, title, description,
                location_text, location, location_confidence,
                workplace_type, employment_type, salary,
                published_at, canonical_url,
                created_at, updated_at
            )
            VALUES(
                %s, %s, %s, %s,
                %s,
                CASE
                    WHEN %s::double precision IS NULL
                      OR %s::double precision IS NULL
                    THEN NULL
                    ELSE extensions.st_point(
                        %s::double precision,
                        %s::double precision
                    )::extensions.geography
                END,
                %s, %s, %s, %s,
                %s, %s, %s, %s
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
                created_at = LEAST(
                    public.opportunities.created_at,
                    excluded.created_at
                ),
                updated_at = GREATEST(
                    public.opportunities.updated_at,
                    excluded.updated_at
                )
            """,
            (
                opportunity_id,
                job.company or "",
                job.title or "",
                job.description or "",
                job.location or "",
                job.latitude,
                job.longitude,
                job.longitude,
                job.latitude,
                job.location_confidence,
                job.workplace_type,
                job.employment_type,
                job.salary,
                job.published_at,
                canonical,
                first_seen,
                last_changed,
            ),
        )

        self.conn.execute(
            """
            INSERT INTO public.source_postings(
                source, source_job_id, opportunity_id,
                url, source_type, normalized_job_json,
                raw_hash, processing_version,
                first_seen_at, last_seen_at, last_checked_at,
                last_changed_at, is_active,
                missing_since, inactive_at, miss_count, seen_count,
                association_method, associated_at
            )
            VALUES(
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, true,
                NULL, NULL, 0, 0,
                'identity', %s
            )
            ON CONFLICT(source, source_job_id) DO UPDATE SET
                url = excluded.url,
                source_type = excluded.source_type,
                normalized_job_json = excluded.normalized_job_json,
                raw_hash = excluded.raw_hash,
                processing_version = excluded.processing_version,
                last_seen_at = excluded.last_seen_at,
                last_changed_at = excluded.last_changed_at,
                is_active = true
            """,
            (
                job.source,
                job.source_job_id,
                opportunity_id,
                job.url or "",
                job.source_type or "official_api",
                Jsonb(payload),
                new_hash,
                version,
                first_seen,
                now,
                now,
                last_changed,
                first_seen,
            ),
        )
        dirty = getattr(self, "_association_dirty_keys", None)
        if dirty is None:
            dirty = self._association_dirty_keys = set()
        dirty.add((str(job.source), str(job.source_job_id)))
        return opportunity_id

    def _sync_opportunity_classification(self, opportunity_id: str) -> None:
        """Rebuild course scores and intents from every posting in an opportunity."""
        rows = self.conn.execute(
            """
            SELECT normalized_job_json
            FROM public.source_postings
            WHERE opportunity_id = %s
            ORDER BY source, source_job_id
            """,
            (opportunity_id,),
        ).fetchall()

        scores: dict[str, int] = {}
        intents: set[str] = set()
        for row in rows:
            payload = dict(row["normalized_job_json"] or {})
            for course_id, score in _course_scores(payload).items():
                scores[course_id] = max(scores.get(course_id, 0), score)
            intents.update(_intents(payload))

        self.conn.execute(
            """
            DELETE FROM public.opportunity_course_scores
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        if scores:
            with self.conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO public.opportunity_course_scores(
                        opportunity_id, course_id, score
                    )
                    VALUES(%s, %s, %s)
                    """,
                    [
                        (opportunity_id, course_id, score)
                        for course_id, score in sorted(scores.items())
                    ],
                )

        self.conn.execute(
            """
            DELETE FROM public.opportunity_intents
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        if intents:
            with self.conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO public.opportunity_intents(
                        opportunity_id, intent_id
                    )
                    VALUES(%s, %s)
                    """,
                    [
                        (opportunity_id, intent_id)
                        for intent_id in sorted(intents)
                    ],
                )

    def upsert_posting(
        self,
        job: Job,
        *,
        seen_at: str | None = None,
        processing_version: str | None = None,
        commit: bool = False,
    ) -> None:
        """Persist a processed posting and refresh relational classification."""
        opportunity_id = self._upsert_posting_core(
            job,
            seen_at=seen_at,
            processing_version=processing_version,
        )
        self._sync_opportunity_classification(opportunity_id)
        if commit:
            self.commit()

    def touch_posting(
        self,
        source: str,
        source_job_id: str,
        *,
        seen_at: str | None = None,
        commit: bool = False,
    ) -> None:
        """Refresh a known posting without reprocessing its normalized payload."""
        now = seen_at or _utcnow()
        self.conn.execute(
            """
            UPDATE public.source_postings
            SET last_seen_at = %s,
                is_active = true
            WHERE source = %s AND source_job_id = %s
            """,
            (now, source, source_job_id),
        )
        if commit:
            self.commit()

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

    def mark_seen_ids(
        self,
        source: str,
        source_job_ids: Iterable[str],
        *,
        scope_status: str = "catalog",
        seen_at: str | None = None,
    ) -> dict[str, int]:
        """Reset missing/inactive state for IDs that were positively observed."""
        now = seen_at or _utcnow()
        ids = sorted({str(value) for value in source_job_ids if str(value)})
        if not ids:
            return {"seen": 0, "reopened": 0}

        self.record_discoveries(
            source,
            ids,
            scope_status=scope_status,
            seen_at=now,
        )

        reopened_row = self.conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM public.source_postings
            WHERE source = %s
              AND source_job_id = ANY(%s)
              AND (NOT is_active OR miss_count > 0)
            """,
            (source, ids),
        ).fetchone()
        reopened = int(reopened_row["n"] or 0)

        self.conn.execute(
            """
            UPDATE public.source_postings
            SET last_seen_at = %s,
                last_checked_at = %s,
                seen_count = seen_count + 1,
                miss_count = 0,
                missing_since = NULL,
                inactive_at = NULL,
                is_active = true
            WHERE source = %s
              AND source_job_id = ANY(%s)
            """,
            (now, now, source, ids),
        )
        return {"seen": len(ids), "reopened": reopened}

    def mark_seen_postings(
        self,
        jobs: Iterable[Job],
        *,
        seen_at: str | None = None,
    ) -> dict[str, int]:
        """Mark a collection of source-native postings as positively observed."""
        grouped: dict[str, set[str]] = defaultdict(set)
        for job in jobs:
            grouped[str(job.source)].add(str(job.source_job_id))

        total_seen = 0
        reopened = 0
        for source, ids in grouped.items():
            result = self.mark_seen_ids(
                source,
                ids,
                scope_status="catalog",
                seen_at=seen_at,
            )
            total_seen += result["seen"]
            reopened += result["reopened"]
        return {"seen": total_seen, "reopened": reopened}

    def reconcile_scope(
        self,
        source: str,
        seen_source_job_ids: Iterable[str],
        *,
        prefix: str | None = None,
        coverage: str = "partial",
        miss_threshold: int = 2,
        checked_at: str | None = None,
    ) -> dict[str, Any]:
        """Advance lifecycle only after a provably complete source scan."""
        now = checked_at or _utcnow()
        seen = {str(value) for value in seen_source_job_ids if str(value)}
        result: dict[str, Any] = {
            "coverage": coverage,
            "checked": 0,
            "seen": len(seen),
            "new_missing": 0,
            "inactivated": 0,
            "skipped": coverage != "complete",
        }
        if coverage != "complete":
            return result

        threshold = max(2, int(miss_threshold or 2))
        select_sql = """
            SELECT source_job_id, is_active, miss_count, missing_since
            FROM public.source_postings
            WHERE source = %s
        """
        select_args: list[Any] = [source]
        if prefix is not None:
            select_sql += " AND source_job_id LIKE %s"
            select_args.append(prefix + "%")

        rows = self.conn.execute(select_sql, select_args).fetchall()
        result["checked"] = len(rows)

        check_sql = """
            UPDATE public.source_postings
            SET last_checked_at = %s
            WHERE source = %s
        """
        check_args: list[Any] = [now, source]
        if prefix is not None:
            check_sql += " AND source_job_id LIKE %s"
            check_args.append(prefix + "%")
        self.conn.execute(check_sql, check_args)

        updates = []
        for row in rows:
            source_job_id = str(row["source_job_id"])
            if source_job_id in seen or not bool(row["is_active"]):
                continue

            old_miss = int(row["miss_count"] or 0)
            new_miss = old_miss + 1
            inactive = new_miss >= threshold
            if old_miss == 0:
                result["new_missing"] += 1
            if inactive:
                result["inactivated"] += 1

            updates.append(
                (
                    new_miss,
                    now,
                    inactive,
                    now,
                    inactive,
                    source,
                    source_job_id,
                )
            )

        if updates:
            with self.conn.cursor() as cur:
                cur.executemany(
                    """
                    UPDATE public.source_postings
                    SET miss_count = %s,
                        missing_since = COALESCE(missing_since, %s),
                        inactive_at = CASE
                            WHEN %s THEN COALESCE(inactive_at, %s)
                            ELSE inactive_at
                        END,
                        is_active = CASE
                            WHEN %s THEN false
                            ELSE is_active
                        END
                    WHERE source = %s AND source_job_id = %s
                    """,
                    updates,
                )
        return result

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


    def _sync_group_classification(
        self,
        opportunity_id: str,
        group: list[Job],
    ) -> None:
        scores: dict[str, int] = {}
        intents: set[str] = set()
        for job in group:
            for course_id, raw_score in (job.course_scores or {}).items():
                course_id = str(course_id)
                score = int(raw_score)
                scores[course_id] = max(scores.get(course_id, 0), score)
            intents.update(
                str(intent).strip()
                for intent in (job.detected_intents or [])
                if str(intent).strip()
            )

        self.conn.execute(
            """
            DELETE FROM public.opportunity_course_scores
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        if scores:
            with self.conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO public.opportunity_course_scores(
                        opportunity_id, course_id, score
                    )
                    VALUES(%s, %s, %s)
                    """,
                    [
                        (opportunity_id, course_id, score)
                        for course_id, score in sorted(scores.items())
                    ],
                )

        self.conn.execute(
            """
            DELETE FROM public.opportunity_intents
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        )
        if intents:
            with self.conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO public.opportunity_intents(
                        opportunity_id, intent_id
                    )
                    VALUES(%s, %s)
                    """,
                    [
                        (opportunity_id, intent_id)
                        for intent_id in sorted(intents)
                    ],
                )

    def _upsert_opportunity_group(
        self,
        opportunity_id: str,
        group: list[Job],
        times: dict[tuple[str, str], tuple[Any, Any]],
    ) -> None:
        merged = deduplicate_jobs(group)[0]
        created_at = min(
            times[(job.source, job.source_job_id)][0]
            for job in group
        )
        updated_at = max(
            times[(job.source, job.source_job_id)][1]
            for job in group
        )
        canonical = canonical_job_url(merged.url) or merged.url or None

        self.conn.execute(
            """
            INSERT INTO public.opportunities(
                id, company, title, description,
                location_text, location, location_confidence,
                workplace_type, employment_type, salary,
                published_at, canonical_url,
                created_at, updated_at
            )
            VALUES(
                %s, %s, %s, %s,
                %s,
                CASE
                    WHEN %s::double precision IS NULL
                      OR %s::double precision IS NULL
                    THEN NULL
                    ELSE extensions.st_point(
                        %s::double precision,
                        %s::double precision
                    )::extensions.geography
                END,
                %s, %s, %s, %s,
                %s, %s, %s, %s
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
            """,
            (
                opportunity_id,
                merged.company or "",
                merged.title or "",
                merged.description or "",
                merged.location or "",
                merged.latitude,
                merged.longitude,
                merged.longitude,
                merged.latitude,
                merged.location_confidence,
                merged.workplace_type,
                merged.employment_type,
                merged.salary,
                merged.published_at,
                canonical,
                created_at,
                updated_at,
            ),
        )
        self._sync_group_classification(opportunity_id, group)

    def _association_stats(self) -> dict[str, int]:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1
                        FROM public.source_postings p
                        WHERE p.opportunity_id = o.id
                          AND p.is_active
                    )
                ) AS active_opportunities,
                COUNT(*) FILTER (
                    WHERE (
                        SELECT COUNT(DISTINCT p.source)
                        FROM public.source_postings p
                        WHERE p.opportunity_id = o.id
                    ) > 1
                ) AS cross_source_opportunities
            FROM public.opportunities o
            """
        ).fetchone()
        associated = self.conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM public.source_postings
            WHERE association_method = 'conservative_url'
            """
        ).fetchone()
        return {
            "active_opportunities": int(row["active_opportunities"] or 0),
            "cross_source_opportunities": int(
                row["cross_source_opportunities"] or 0
            ),
            "associated_postings": int(associated["n"] or 0),
        }

    def sync_unified_schema(self, *, commit: bool = True) -> dict[str, Any]:
        """Reconcile PostgreSQL opportunities with CP4 conservative identity."""
        rows = self.conn.execute(
            """
            SELECT
                source, source_job_id, opportunity_id,
                association_method, associated_at,
                normalized_job_json,
                first_seen_at, last_changed_at
            FROM public.source_postings
            ORDER BY source, source_job_id
            """
        ).fetchall()

        dirty = set(getattr(self, "_association_dirty_keys", set()))
        plan = _association_plan(rows, dirty_keys=dirty)
        associated_at = _utcnow()
        rebuilt = 0

        try:
            for opportunity_id in sorted(plan["affected_opportunity_ids"]):
                group = plan["groups_by_opportunity"].get(opportunity_id)
                if group is None:
                    continue
                self._upsert_opportunity_group(
                    opportunity_id,
                    group,
                    plan["times"],
                )
                rebuilt += 1

            if plan["link_updates"]:
                with self.conn.cursor() as cur:
                    cur.executemany(
                        """
                        UPDATE public.source_postings
                        SET opportunity_id = %s,
                            association_method = %s,
                            associated_at = %s
                        WHERE source = %s AND source_job_id = %s
                        """,
                        [
                            (
                                opportunity_id,
                                method,
                                associated_at,
                                source,
                                source_job_id,
                            )
                            for opportunity_id, method, source, source_job_id
                            in plan["link_updates"]
                        ],
                    )

            self.conn.execute(
                """
                DELETE FROM public.opportunities o
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM public.source_postings p
                    WHERE p.opportunity_id = o.id
                )
                """
            )

            if commit:
                self.conn.commit()
                self._association_dirty_keys.clear()
        except Exception:
            if commit:
                self.conn.rollback()
            raise

        stats = self.stats()
        stats.update(self._association_stats())
        stats.update(
            {
                "association_groups": len(plan["groups"]),
                "association_changes": len(plan["link_updates"]),
                "opportunities_rebuilt": rebuilt,
            }
        )
        return stats

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
