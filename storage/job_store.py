"""Persistent incremental store for Opportunity Radar jobs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

from models.job import Job
from processing.deduplicate import deduplicate_source_jobs, source_references
from processing.geolocation import is_remote
from processing.text import normalize

DEFAULT_DB_PATH = Path(os.getenv("OPPORTUNITY_DB_PATH", "data/opportunity_radar.db"))
PROCESSING_VERSION = "3.15.4"
# Source signals consumed by classification and regional location processing.
# Derived scores, resolved locations and collection diagnostics are excluded.
_LOCATION_METADATA_KEYS = ("gupy_city", "gupy_state", "gupy_country")
_PROCESSING_METADATA_KEYS = ("gupy_job_type", "source_level", *_LOCATION_METADATA_KEYS)
_DERIVED_LOCATION_KEYS = ("resolved_city", "resolved_country", "search_distance_km")
_JOB_FIELDS = {f.name for f in fields(Job)}
_STORE_METADATA_KEYS = {
    "store_first_seen_at",
    "store_last_seen_at",
    "store_last_changed_at",
    "store_is_active",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_from_dict(data: dict) -> Job:
    values = {key: value for key, value in data.items() if key in _JOB_FIELDS}
    values.setdefault("metadata", {})
    values.setdefault("detected_intents", [])
    values.setdefault("course_scores", {})
    return Job(**values)


def _clean_metadata(metadata: dict | None) -> dict:
    metadata = dict(metadata or {})
    for key in _STORE_METADATA_KEYS:
        metadata.pop(key, None)
    return metadata


def raw_content_hash(job: Job) -> str:
    """Hash source content, excluding derived classification/geocoding metadata."""
    payload = {
        "source": job.source,
        "source_job_id": job.source_job_id,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "url": job.url,
        "description": job.description,
        "published_at": job.published_at,
        "employment_type": job.employment_type,
        "workplace_type": job.workplace_type,
        "source_type": job.source_type,
        "salary": job.salary,
        "processing_metadata": {
            key: (job.metadata or {}).get(key) or None
            for key in _PROCESSING_METADATA_KEYS
        },
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _merge_cached_fields(incoming: Job, cached: Job) -> Job:
    """Reuse expensive/detail fields when collection returns a lightweight stub."""
    for attr in (
        "description",
        "location",
        "published_at",
        "employment_type",
        "workplace_type",
        "salary",
    ):
        if not getattr(incoming, attr, None) and getattr(cached, attr, None):
            setattr(incoming, attr, getattr(cached, attr))

    metadata = _clean_metadata(cached.metadata)
    text_changed = normalize(incoming.location) != normalize(cached.location)
    if text_changed:
        # An old structured city must not override the new textual location.
        for key in _LOCATION_METADATA_KEYS:
            metadata.pop(key, None)
    metadata.update(_clean_metadata(incoming.metadata))
    references = source_references(cached, incoming)
    if len(references) > 1 or "source_references" in metadata:
        metadata["source_references"] = references
    location_changed = (
        text_changed
        or is_remote(incoming) != is_remote(cached)
        or any(
            normalize(str(metadata.get(key) or ""))
            != normalize(str((cached.metadata or {}).get(key) or ""))
            for key in _LOCATION_METADATA_KEYS
        )
    )
    if location_changed:
        for key in _DERIVED_LOCATION_KEYS:
            metadata.pop(key, None)
        # Gupy also supplies this country directly, including countries the
        # text geocoder cannot infer. Keep a fresh source value, never the cache.
        if (incoming.metadata or {}).get("resolved_country"):
            metadata["resolved_country"] = incoming.metadata["resolved_country"]
        # Preserve a complete, fresh coordinate pair supplied by the source.
        # Never combine one new coordinate with one cached coordinate.
        if incoming.latitude is None or incoming.longitude is None:
            incoming.latitude = incoming.longitude = None
            incoming.location_confidence = None
    elif incoming.latitude is None and incoming.longitude is None:
        incoming.latitude = cached.latitude
        incoming.longitude = cached.longitude
        incoming.location_confidence = cached.location_confidence

    incoming.metadata = metadata

    if not incoming.detected_intents and cached.detected_intents:
        incoming.detected_intents = list(cached.detected_intents)
    if not incoming.course_scores and cached.course_scores:
        incoming.course_scores = dict(cached.course_scores)
    return incoming


class JobStore:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._cache: dict[tuple[str, str], sqlite3.Row] | None = None
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                source TEXT NOT NULL,
                source_job_id TEXT NOT NULL,
                job_json TEXT NOT NULL,
                raw_hash TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_changed_at TEXT NOT NULL,
                processing_version TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (source, source_job_id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_source
                ON jobs(source);

            CREATE INDEX IF NOT EXISTS idx_jobs_last_seen
                ON jobs(last_seen_at);

            CREATE TABLE IF NOT EXISTS store_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO store_meta(key, value) VALUES('schema_version', '1')"
        )
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()
        self._cache = None

    def _index(self) -> dict[tuple[str, str], sqlite3.Row]:
        if self._cache is None:
            rows = self.conn.execute("SELECT * FROM jobs").fetchall()
            self._cache = {
                (row["source"], row["source_job_id"]): row
                for row in rows
            }
        return self._cache

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def known_ids(self, source: str, *, prefix: str | None = None) -> set[str]:
        ids = {
            source_job_id
            for src, source_job_id in self._index()
            if src == source
        }
        if prefix is not None:
            ids = {value for value in ids if value.startswith(prefix)}
        return ids

    def prepare(self, incoming: Job) -> tuple[Job, str, bool]:
        """Return (job, status, needs_processing)."""
        row = self._index().get((incoming.source, incoming.source_job_id))
        if row is None:
            return incoming, "new", True

        cached = self._row_to_job(row)
        candidate = _merge_cached_fields(incoming, cached)
        same_raw = raw_content_hash(candidate) == row["raw_hash"]

        if same_raw and row["processing_version"] == PROCESSING_VERSION:
            references = candidate.metadata.get("source_references")
            if references != cached.metadata.get("source_references"):
                # Retain new references without reclassifying. The caller
                # still commits this metadata-only update with the batch.
                cached.metadata["source_references"] = references
                self.upsert(cached, commit=False)
            return cached, "unchanged", False
        if same_raw:
            return candidate, "reprocess", True
        return candidate, "changed", True

    def touch(
        self,
        source: str,
        source_job_id: str,
        *,
        seen_at: str | None = None,
        commit: bool = False,
    ) -> None:
        seen_at = seen_at or _utcnow()
        self.conn.execute(
            """
            UPDATE jobs
            SET last_seen_at = ?, is_active = 1
            WHERE source = ? AND source_job_id = ?
            """,
            (seen_at, source, source_job_id),
        )
        if commit:
            self.commit()

    def upsert(
        self,
        job: Job,
        *,
        seen_at: str | None = None,
        processing_version: str = PROCESSING_VERSION,
        commit: bool = False,
    ) -> None:
        seen_at = seen_at or _utcnow()
        old = self._index().get((job.source, job.source_job_id))
        first_seen = old["first_seen_at"] if old else seen_at
        new_hash = raw_content_hash(job)
        last_changed = (
            old["last_changed_at"]
            if old is not None and old["raw_hash"] == new_hash
            else seen_at
        )

        payload_data = job.to_dict()
        payload_data["metadata"] = _clean_metadata(payload_data.get("metadata"))
        payload = json.dumps(
            payload_data,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

        self.conn.execute(
            """
            INSERT INTO jobs(
                source, source_job_id, job_json, raw_hash,
                first_seen_at, last_seen_at, last_changed_at,
                processing_version, is_active
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(source, source_job_id) DO UPDATE SET
                job_json = excluded.job_json,
                raw_hash = excluded.raw_hash,
                last_seen_at = excluded.last_seen_at,
                last_changed_at = excluded.last_changed_at,
                processing_version = excluded.processing_version,
                is_active = 1
            """,
            (
                job.source,
                job.source_job_id,
                payload,
                new_hash,
                first_seen,
                seen_at,
                last_changed,
                processing_version,
            ),
        )
        if commit:
            self.commit()

    def bootstrap_from_json(self, path: str | Path) -> dict:
        """Seed a new DB from an existing exported output/jobs.json."""
        path = Path(path)
        if self.count() > 0 or not path.exists():
            return {"imported": 0, "path": str(path)}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"imported": 0, "path": str(path)}

        if not isinstance(data, list):
            return {"imported": 0, "path": str(path)}

        now = _utcnow()
        before = self.count()
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                job = _job_from_dict(item)
            except (TypeError, ValueError):
                continue
            self.upsert(job, seen_at=now, commit=False)
        self.commit()
        return {"imported": self.count() - before, "path": str(path)}

    def load_jobs(self, *, active_only: bool = True) -> list[Job]:
        sql = "SELECT * FROM jobs"
        if active_only:
            sql += " WHERE is_active = 1"
        rows = self.conn.execute(sql).fetchall()
        return [self._row_to_job(row) for row in rows]

    def stats(self) -> dict:
        total = int(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        active = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_active = 1"
            ).fetchone()[0]
        )
        by_source = {
            row["source"]: int(row["n"])
            for row in self.conn.execute(
                "SELECT source, COUNT(*) AS n "
                "FROM jobs GROUP BY source ORDER BY n DESC"
            ).fetchall()
        }
        return {
            "path": str(self.path),
            "total_jobs": total,
            "active_jobs": active,
            "by_source": by_source,
            "processing_version": PROCESSING_VERSION,
        }

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        data = json.loads(row["job_json"])
        job = _job_from_dict(data)
        metadata = _clean_metadata(job.metadata)
        metadata["store_first_seen_at"] = row["first_seen_at"]
        metadata["store_last_seen_at"] = row["last_seen_at"]
        metadata["store_last_changed_at"] = row["last_changed_at"]
        metadata["store_is_active"] = bool(row["is_active"])
        job.metadata = metadata
        return job
