"""Checkpoint 4-A: shadow relational schema for unified persistence.

The legacy ``jobs`` table remains the runtime source of truth during CP4-A.
This module mirrors it into a normalized relational model so migration can be
validated before the pipeline starts reading/writing the new repository layer.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from models.job import Job
from processing.deduplicate import (
    canonical_job_url,
    deduplicate_job_groups,
    deduplicate_jobs,
)
from storage.incremental_state import ensure_incremental_schema

UNIFIED_SCHEMA_VERSION = "4"
UNIFIED_ASSOCIATION_VERSION = "1"
UNIFIED_CLASSIFICATION_VERSION = "1"
UNIFIED_SHADOW_MODE = "legacy_jobs_1to1"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class UnifiedSchemaError(RuntimeError):
    """Raised when the legacy store cannot be migrated without data loss."""


def _stable_opportunity_id(source: str, source_job_id: str) -> str:
    """Return a deterministic UUID for the initial 1-posting/1-opportunity map."""
    identity = json.dumps(
        [str(source), str(source_job_id)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "opportunity-radar:" + identity,
        )
    )


def _create_schema(conn: sqlite3.Connection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS opportunities (
            id TEXT PRIMARY KEY,
            company TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            location_text TEXT NOT NULL DEFAULT '',
            latitude REAL,
            longitude REAL,
            location_confidence TEXT,
            workplace_type TEXT,
            employment_type TEXT,
            salary TEXT,
            published_at TEXT,
            canonical_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS source_postings (
            source TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            opportunity_id TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'official_api',
            normalized_job_json TEXT NOT NULL,
            raw_hash TEXT NOT NULL,
            processing_version TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_checked_at TEXT,
            last_changed_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            missing_since TEXT,
            inactive_at TEXT,
            miss_count INTEGER NOT NULL DEFAULT 0,
            seen_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (source, source_job_id),
            FOREIGN KEY (opportunity_id)
                REFERENCES opportunities(id)
                ON DELETE RESTRICT
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_source_postings_opportunity
            ON source_postings(opportunity_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_source_postings_active
            ON source_postings(is_active)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_source_postings_last_seen
            ON source_postings(last_seen_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS opportunity_course_scores (
            opportunity_id TEXT NOT NULL,
            course_id TEXT NOT NULL,
            score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
            PRIMARY KEY (opportunity_id, course_id),
            FOREIGN KEY (opportunity_id)
                REFERENCES opportunities(id)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS opportunity_intents (
            opportunity_id TEXT NOT NULL,
            intent_id TEXT NOT NULL,
            PRIMARY KEY (opportunity_id, intent_id),
            FOREIGN KEY (opportunity_id)
                REFERENCES opportunities(id)
                ON DELETE CASCADE
        )
        """,
    ]
    for statement in statements:
        conn.execute(statement)


def _json_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(row["job_json"])
    except Exception as exc:
        raise UnifiedSchemaError(
            "job_json inválido para "
            f"{row['source']}:{row['source_job_id']}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise UnifiedSchemaError(
            "job_json não é objeto para "
            f"{row['source']}:{row['source_job_id']}"
        )
    return payload


def _course_scores(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("course_scores") or {}
    if not isinstance(raw, dict):
        raise UnifiedSchemaError("course_scores não é objeto")

    result: dict[str, int] = {}
    for course_id, value in raw.items():
        course_id = str(course_id).strip()
        if not course_id:
            continue
        try:
            score = int(value)
        except (TypeError, ValueError) as exc:
            raise UnifiedSchemaError(
                f"score inválido para curso {course_id!r}: {value!r}"
            ) from exc
        if not 0 <= score <= 100:
            raise UnifiedSchemaError(
                f"score fora de 0..100 para curso {course_id!r}: {score}"
            )
        result[course_id] = score
    return result


def _intents(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("detected_intents") or []
    if not isinstance(raw, list):
        raise UnifiedSchemaError("detected_intents não é lista")
    return sorted({str(value).strip() for value in raw if str(value).strip()})


def ensure_unified_schema(store) -> dict[str, Any]:
    """Create/sync the CP4-A shadow schema from the legacy ``jobs`` table.

    CP4-A intentionally performs no cross-source merge. Every legacy posting
    receives one deterministic opportunity. Later CP4 stages may associate
    multiple postings after conservative identity evidence is persisted.
    """
    # Guarantees lifecycle columns/tables exist before they are mirrored.
    ensure_incremental_schema(store)

    conn = store.conn
    conn.execute("PRAGMA foreign_keys = ON")

    rows = conn.execute(
        """
        SELECT *
        FROM jobs
        ORDER BY source, source_job_id
        """
    ).fetchall()

    migrated_scores = 0
    migrated_intents = 0

    try:
        conn.execute("BEGIN IMMEDIATE")
        _create_schema(conn)

        for row in rows:
            source = str(row["source"])
            source_job_id = str(row["source_job_id"])
            opportunity_id = _stable_opportunity_id(source, source_job_id)
            payload = _json_payload(row)

            url = str(payload.get("url") or "")
            canonical = canonical_job_url(url) or url or None
            first_seen = str(row["first_seen_at"])
            last_seen = str(row["last_seen_at"])
            last_changed = str(row["last_changed_at"])
            last_checked = row["last_checked_at"] or last_seen

            conn.execute(
                """
                INSERT INTO opportunities(
                    id, company, title, description,
                    location_text, latitude, longitude,
                    location_confidence, workplace_type, employment_type,
                    salary, published_at, canonical_url,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    company = excluded.company,
                    title = excluded.title,
                    description = excluded.description,
                    location_text = excluded.location_text,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
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
                    str(payload.get("company") or ""),
                    str(payload.get("title") or ""),
                    str(payload.get("description") or ""),
                    str(payload.get("location") or ""),
                    payload.get("latitude"),
                    payload.get("longitude"),
                    payload.get("location_confidence"),
                    payload.get("workplace_type"),
                    payload.get("employment_type"),
                    payload.get("salary"),
                    payload.get("published_at"),
                    canonical,
                    first_seen,
                    last_changed,
                ),
            )

            conn.execute(
                """
                INSERT INTO source_postings(
                    source, source_job_id, opportunity_id,
                    url, source_type, normalized_job_json,
                    raw_hash, processing_version,
                    first_seen_at, last_seen_at, last_checked_at,
                    last_changed_at, is_active,
                    missing_since, inactive_at, miss_count, seen_count
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_job_id) DO UPDATE SET
                    opportunity_id = source_postings.opportunity_id,
                    url = excluded.url,
                    source_type = excluded.source_type,
                    normalized_job_json = excluded.normalized_job_json,
                    raw_hash = excluded.raw_hash,
                    processing_version = excluded.processing_version,
                    first_seen_at = excluded.first_seen_at,
                    last_seen_at = excluded.last_seen_at,
                    last_checked_at = excluded.last_checked_at,
                    last_changed_at = excluded.last_changed_at,
                    is_active = excluded.is_active,
                    missing_since = excluded.missing_since,
                    inactive_at = excluded.inactive_at,
                    miss_count = excluded.miss_count,
                    seen_count = excluded.seen_count
                """,
                (
                    source,
                    source_job_id,
                    opportunity_id,
                    url,
                    str(payload.get("source_type") or "official_api"),
                    row["job_json"],
                    str(row["raw_hash"]),
                    str(row["processing_version"]),
                    first_seen,
                    last_seen,
                    last_checked,
                    last_changed,
                    int(row["is_active"]),
                    row["missing_since"],
                    row["inactive_at"],
                    int(row["miss_count"] or 0),
                    int(row["seen_count"] or 0),
                ),
            )

            # The shadow opportunity is 1:1 with the posting in CP4-A, so its
            # classification is replaced exactly with the latest legacy value.
            conn.execute(
                "DELETE FROM opportunity_course_scores WHERE opportunity_id = ?",
                (opportunity_id,),
            )
            scores = _course_scores(payload)
            if scores:
                conn.executemany(
                    """
                    INSERT INTO opportunity_course_scores(
                        opportunity_id, course_id, score
                    )
                    VALUES(?, ?, ?)
                    """,
                    [
                        (opportunity_id, course_id, score)
                        for course_id, score in sorted(scores.items())
                    ],
                )
            migrated_scores += len(scores)

            conn.execute(
                "DELETE FROM opportunity_intents WHERE opportunity_id = ?",
                (opportunity_id,),
            )
            intents = _intents(payload)
            if intents:
                conn.executemany(
                    """
                    INSERT INTO opportunity_intents(opportunity_id, intent_id)
                    VALUES(?, ?)
                    """,
                    [(opportunity_id, intent_id) for intent_id in intents],
                )
            migrated_intents += len(intents)

        conn.execute(
            """
            INSERT OR REPLACE INTO store_meta(key, value)
            VALUES('unified_schema_version', ?)
            """,
            (UNIFIED_SCHEMA_VERSION,),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO store_meta(key, value)
            VALUES('unified_shadow_mode', ?)
            """,
            (UNIFIED_SHADOW_MODE,),
        )

        validation = validate_unified_schema(store, require_tables=True)
        if not validation["ok"]:
            raise UnifiedSchemaError(
                "validação CP4-A falhou antes do commit: "
                + json.dumps(validation, ensure_ascii=False, default=str)
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    stats = unified_schema_stats(store)
    stats.update(
        {
            "legacy_jobs_scanned": len(rows),
            "course_scores_synced": migrated_scores,
            "intents_synced": migrated_intents,
            "schema_version": UNIFIED_SCHEMA_VERSION,
            "shadow_mode": UNIFIED_SHADOW_MODE,
        }
    )
    return stats


def unified_schema_stats(store) -> dict[str, int]:
    conn = store.conn

    def count(table: str) -> int:
        exists = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table,),
        ).fetchone()
        if not exists:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    return {
        "opportunities": count("opportunities"),
        "source_postings": count("source_postings"),
        "course_scores": count("opportunity_course_scores"),
        "intents": count("opportunity_intents"),
    }


def validate_unified_schema(
    store,
    *,
    require_tables: bool = False,
) -> dict[str, Any]:
    """Check lossless legacy->shadow coverage without mutating the database."""
    conn = store.conn
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
    missing_tables = sorted(required - present)

    if missing_tables:
        return {
            "ok": False if require_tables else True,
            "missing_tables": missing_tables,
            "missing_postings": 0,
            "broken_opportunity_links": 0,
            "lifecycle_mismatches": 0,
            "foreign_key_violations": 0,
        }

    missing_postings = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM jobs j
            LEFT JOIN source_postings p
              ON p.source = j.source
             AND p.source_job_id = j.source_job_id
            WHERE p.source IS NULL
            """
        ).fetchone()[0]
    )

    broken_links = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM source_postings p
            LEFT JOIN opportunities o
              ON o.id = p.opportunity_id
            WHERE o.id IS NULL
            """
        ).fetchone()[0]
    )

    lifecycle_mismatches = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM jobs j
            JOIN source_postings p
              ON p.source = j.source
             AND p.source_job_id = j.source_job_id
            WHERE p.is_active IS NOT j.is_active
               OR p.last_seen_at IS NOT j.last_seen_at
               OR p.last_checked_at IS NOT COALESCE(j.last_checked_at, j.last_seen_at)
               OR p.missing_since IS NOT j.missing_since
               OR p.inactive_at IS NOT j.inactive_at
               OR p.miss_count IS NOT j.miss_count
               OR p.seen_count IS NOT j.seen_count
            """
        ).fetchone()[0]
    )

    fk_violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())

    return {
        "ok": (
            not missing_tables
            and missing_postings == 0
            and broken_links == 0
            and lifecycle_mismatches == 0
            and fk_violations == 0
        ),
        "missing_tables": missing_tables,
        "missing_postings": missing_postings,
        "broken_opportunity_links": broken_links,
        "lifecycle_mismatches": lifecycle_mismatches,
        "foreign_key_violations": fk_violations,
    }


def _ensure_association_columns(conn) -> None:
    columns = {
        str(row[1])
        for row in conn.execute(
            "PRAGMA table_info(source_postings)"
        ).fetchall()
    }
    if "association_method" not in columns:
        conn.execute(
            "ALTER TABLE source_postings "
            "ADD COLUMN association_method TEXT NOT NULL DEFAULT 'identity'"
        )
    if "associated_at" not in columns:
        conn.execute(
            "ALTER TABLE source_postings ADD COLUMN associated_at TEXT"
        )


def _association_stats(store) -> dict:
    conn = store.conn
    active_opportunities = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM opportunities o
            WHERE EXISTS (
                SELECT 1
                FROM source_postings p
                WHERE p.opportunity_id = o.id
                  AND p.is_active = 1
            )
            """
        ).fetchone()[0]
    )
    cross_source_opportunities = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT opportunity_id
                FROM source_postings
                GROUP BY opportunity_id
                HAVING COUNT(DISTINCT source) > 1
            )
            """
        ).fetchone()[0]
    )
    associated_postings = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM source_postings
            WHERE association_method = 'conservative_url'
            """
        ).fetchone()[0]
    )
    return {
        "active_opportunities": active_opportunities,
        "cross_source_opportunities": cross_source_opportunities,
        "associated_postings": associated_postings,
    }


def _unified_tables_ready(conn) -> bool:
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
    return required <= present


def _insert_new_shadow_posting(conn, row) -> tuple[str, str]:
    source = str(row["source"])
    source_job_id = str(row["source_job_id"])
    opportunity_id = _stable_opportunity_id(source, source_job_id)
    payload = _json_payload(row)

    first_seen = str(row["first_seen_at"])
    last_seen = str(row["last_seen_at"])
    last_changed = str(row["last_changed_at"])
    last_checked = row["last_checked_at"] or last_seen

    job = Job(**{
        key: value
        for key, value in payload.items()
        if key in Job.__dataclass_fields__
    })
    canonical = canonical_job_url(job.url) or job.url or None

    conn.execute(
        """
        INSERT OR IGNORE INTO opportunities(
            id, company, title, description,
            location_text, latitude, longitude,
            location_confidence, workplace_type, employment_type,
            salary, published_at, canonical_url,
            created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            opportunity_id,
            job.company or "",
            job.title or "",
            job.description or "",
            job.location or "",
            job.latitude,
            job.longitude,
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

    conn.execute(
        """
        INSERT INTO source_postings(
            source, source_job_id, opportunity_id,
            url, source_type, normalized_job_json,
            raw_hash, processing_version,
            first_seen_at, last_seen_at, last_checked_at,
            last_changed_at, is_active,
            missing_since, inactive_at, miss_count, seen_count,
            association_method, associated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source,
            source_job_id,
            opportunity_id,
            str(payload.get("url") or ""),
            str(payload.get("source_type") or "official_api"),
            row["job_json"],
            str(row["raw_hash"]),
            str(row["processing_version"]),
            first_seen,
            last_seen,
            last_checked,
            last_changed,
            int(row["is_active"]),
            row["missing_since"],
            row["inactive_at"],
            int(row["miss_count"] or 0),
            int(row["seen_count"] or 0),
            "identity",
            first_seen,
        ),
    )

    scores = _course_scores(payload)
    intents = _intents(payload)
    if scores:
        conn.executemany(
            """
            INSERT OR REPLACE INTO opportunity_course_scores(
                opportunity_id, course_id, score
            )
            VALUES(?, ?, ?)
            """,
            [
                (opportunity_id, course_id, score)
                for course_id, score in sorted(scores.items())
            ],
        )
    if intents:
        conn.executemany(
            """
            INSERT OR REPLACE INTO opportunity_intents(
                opportunity_id, intent_id
            )
            VALUES(?, ?)
            """,
            [
                (opportunity_id, intent_id)
                for intent_id in intents
            ],
        )

    return source, source_job_id


def _sync_unified_postings_delta(store) -> dict:
    """Mirror only rows that differ from the legacy write store."""
    conn = store.conn

    if not _unified_tables_ready(conn):
        base = ensure_unified_schema(store)
        _ensure_association_columns(conn)
        conn.commit()
        return {
            **base,
            "content_changed_keys": set(),
            "posting_rows_synced": int(base["legacy_jobs_scanned"]),
            "initial_backfill": True,
        }

    _ensure_association_columns(conn)
    conn.commit()

    missing_rows = conn.execute(
        """
        SELECT j.*
        FROM jobs j
        LEFT JOIN source_postings p
          ON p.source = j.source
         AND p.source_job_id = j.source_job_id
        WHERE p.source IS NULL
        ORDER BY j.source, j.source_job_id
        """
    ).fetchall()

    changed_rows = conn.execute(
        """
        SELECT j.*,
               CASE
                   WHEN p.normalized_job_json IS NOT j.job_json
                   THEN 1 ELSE 0
               END AS content_changed
        FROM jobs j
        JOIN source_postings p
          ON p.source = j.source
         AND p.source_job_id = j.source_job_id
        WHERE p.normalized_job_json IS NOT j.job_json
           OR p.raw_hash IS NOT j.raw_hash
           OR p.processing_version IS NOT j.processing_version
           OR p.first_seen_at IS NOT j.first_seen_at
           OR p.last_seen_at IS NOT j.last_seen_at
           OR p.last_checked_at IS NOT COALESCE(
                j.last_checked_at, j.last_seen_at
              )
           OR p.last_changed_at IS NOT j.last_changed_at
           OR p.is_active IS NOT j.is_active
           OR p.missing_since IS NOT j.missing_since
           OR p.inactive_at IS NOT j.inactive_at
           OR p.miss_count IS NOT j.miss_count
           OR p.seen_count IS NOT j.seen_count
        ORDER BY j.source, j.source_job_id
        """
    ).fetchall()

    content_changed_keys = {
        (str(row["source"]), str(row["source_job_id"]))
        for row in changed_rows
        if int(row["content_changed"])
    }
    content_changed_keys.update(
        (str(row["source"]), str(row["source_job_id"]))
        for row in missing_rows
    )

    try:
        conn.execute("BEGIN IMMEDIATE")

        for row in missing_rows:
            _insert_new_shadow_posting(conn, row)

        if changed_rows:
            conn.executemany(
                """
                UPDATE source_postings
                SET url = ?,
                    source_type = ?,
                    normalized_job_json = ?,
                    raw_hash = ?,
                    processing_version = ?,
                    first_seen_at = ?,
                    last_seen_at = ?,
                    last_checked_at = ?,
                    last_changed_at = ?,
                    is_active = ?,
                    missing_since = ?,
                    inactive_at = ?,
                    miss_count = ?,
                    seen_count = ?
                WHERE source = ? AND source_job_id = ?
                """,
                [
                    (
                        str(_json_payload(row).get("url") or ""),
                        str(
                            _json_payload(row).get("source_type")
                            or "official_api"
                        ),
                        row["job_json"],
                        str(row["raw_hash"]),
                        str(row["processing_version"]),
                        str(row["first_seen_at"]),
                        str(row["last_seen_at"]),
                        row["last_checked_at"] or row["last_seen_at"],
                        str(row["last_changed_at"]),
                        int(row["is_active"]),
                        row["missing_since"],
                        row["inactive_at"],
                        int(row["miss_count"] or 0),
                        int(row["seen_count"] or 0),
                        str(row["source"]),
                        str(row["source_job_id"]),
                    )
                    for row in changed_rows
                ],
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    stats = unified_schema_stats(store)
    return {
        **stats,
        "legacy_jobs_scanned": store.count(),
        "course_scores_synced": 0,
        "intents_synced": 0,
        "schema_version": UNIFIED_SCHEMA_VERSION,
        "shadow_mode": "legacy_jobs_with_persistent_associations",
        "content_changed_keys": content_changed_keys,
        "posting_rows_synced": len(missing_rows) + len(changed_rows),
        "initial_backfill": False,
    }


def _upsert_affected_opportunity(
    conn,
    opportunity_id: str,
    group: list[Job],
    times: dict[tuple[str, str], tuple[str, str]],
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

    conn.execute(
        """
        INSERT INTO opportunities(
            id, company, title, description,
            location_text, latitude, longitude,
            location_confidence, workplace_type, employment_type,
            salary, published_at, canonical_url,
            created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            company = excluded.company,
            title = excluded.title,
            description = excluded.description,
            location_text = excluded.location_text,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
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

    scores: dict[str, int] = {}
    intents: set[str] = set()
    for job in group:
        for course_id, raw_score in (job.course_scores or {}).items():
            score = int(raw_score)
            scores[course_id] = max(scores.get(course_id, 0), score)
        intents.update(
            str(intent).strip()
            for intent in (job.detected_intents or [])
            if str(intent).strip()
        )

    conn.execute(
        "DELETE FROM opportunity_course_scores WHERE opportunity_id = ?",
        (opportunity_id,),
    )
    if scores:
        conn.executemany(
            """
            INSERT INTO opportunity_course_scores(
                opportunity_id, course_id, score
            )
            VALUES(?, ?, ?)
            """,
            [
                (opportunity_id, course_id, score)
                for course_id, score in sorted(scores.items())
            ],
        )

    conn.execute(
        "DELETE FROM opportunity_intents WHERE opportunity_id = ?",
        (opportunity_id,),
    )
    if intents:
        conn.executemany(
            """
            INSERT INTO opportunity_intents(opportunity_id, intent_id)
            VALUES(?, ?)
            """,
            [
                (opportunity_id, intent_id)
                for intent_id in sorted(intents)
            ],
        )


def rebuild_opportunity_associations(
    store,
    *,
    content_changed_keys: set[tuple[str, str]] | None = None,
) -> dict:
    """Rebuild identity in memory, but write only the changed associations."""
    conn = store.conn
    _ensure_association_columns(conn)
    conn.commit()

    jobs = store.load_jobs(active_only=False)
    groups = deduplicate_job_groups(jobs)

    time_rows = conn.execute(
        """
        SELECT source, source_job_id, first_seen_at, last_changed_at
        FROM jobs
        """
    ).fetchall()
    times = {
        (str(row["source"]), str(row["source_job_id"])): (
            str(row["first_seen_at"]),
            str(row["last_changed_at"]),
        )
        for row in time_rows
    }

    desired_by_key: dict[tuple[str, str], tuple[str, str]] = {}
    groups_by_opportunity: dict[str, list[Job]] = {}

    for group in groups:
        if not group:
            continue
        ordered = sorted(
            group,
            key=lambda job: (
                times[(job.source, job.source_job_id)][0],
                job.source,
                job.source_job_id,
            ),
        )
        anchor = ordered[0]
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

    current_rows = conn.execute(
        """
        SELECT source, source_job_id,
               opportunity_id, association_method, associated_at
        FROM source_postings
        """
    ).fetchall()
    current_by_key = {
        (str(row["source"]), str(row["source_job_id"])): row
        for row in current_rows
    }

    now = _utcnow()
    link_updates = []
    affected_opportunity_ids: set[str] = set()

    for key, (desired_id, desired_method) in desired_by_key.items():
        current = current_by_key.get(key)
        if current is None:
            raise UnifiedSchemaError(
                "source posting ausente durante associação: "
                f"{key[0]}:{key[1]}"
            )

        current_id = str(current["opportunity_id"])
        current_method = str(current["association_method"] or "identity")

        if current_id != desired_id or current_method != desired_method:
            affected_opportunity_ids.add(current_id)
            affected_opportunity_ids.add(desired_id)
            link_updates.append(
                (
                    desired_id,
                    desired_method,
                    now,
                    key[0],
                    key[1],
                )
            )

    for key in content_changed_keys or set():
        desired = desired_by_key.get(key)
        if desired is not None:
            affected_opportunity_ids.add(desired[0])

    try:
        conn.execute("BEGIN IMMEDIATE")

        # FK-safe ordering: a split may move a posting to an opportunity that
        # was previously removed as an orphan. Recreate/update every desired
        # target before changing source_postings.opportunity_id.
        rebuilt = 0
        for opportunity_id in sorted(affected_opportunity_ids):
            group = groups_by_opportunity.get(opportunity_id)
            if group is None:
                continue
            _upsert_affected_opportunity(
                conn,
                opportunity_id,
                group,
                times,
            )
            rebuilt += 1

        if link_updates:
            conn.executemany(
                """
                UPDATE source_postings
                SET opportunity_id = ?,
                    association_method = ?,
                    associated_at = ?
                WHERE source = ? AND source_job_id = ?
                """,
                link_updates,
            )

        # Previous merge/split targets that lost all postings can now disappear.
        conn.execute(
            """
            DELETE FROM opportunities
            WHERE id NOT IN (
                SELECT DISTINCT opportunity_id FROM source_postings
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO store_meta(key, value)
            VALUES('unified_association_version', ?)
            """,
            (UNIFIED_ASSOCIATION_VERSION,),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO store_meta(key, value)
            VALUES('unified_classification_version', ?)
            """,
            (UNIFIED_CLASSIFICATION_VERSION,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        **unified_schema_stats(store),
        **_association_stats(store),
        "association_groups": len(groups),
        "association_changes": len(link_updates),
        "opportunities_rebuilt": rebuilt,
        "association_version": UNIFIED_ASSOCIATION_VERSION,
        "classification_version": UNIFIED_CLASSIFICATION_VERSION,
    }


def sync_unified_persistence(store) -> dict:
    """Incrementally mirror postings and persist only association deltas."""
    base = _sync_unified_postings_delta(store)
    associations = rebuild_opportunity_associations(
        store,
        content_changed_keys=base.pop("content_changed_keys"),
    )
    validation = validate_unified_schema(store, require_tables=True)
    if not validation["ok"]:
        raise UnifiedSchemaError(
            "validação CP4-C falhou após associações: "
            + json.dumps(validation, ensure_ascii=False, default=str)
        )
    return {
        **base,
        **associations,
        "schema_version": UNIFIED_SCHEMA_VERSION,
        "shadow_mode": "legacy_jobs_with_persistent_associations",
    }
