import json

from models.job import Job
from storage.incremental_state import (
    ensure_incremental_schema,
    finish_scope_run,
    record_discoveries,
)
from storage.job_store import JobStore
from storage.unified_schema import (
    UNIFIED_SCHEMA_VERSION,
    ensure_unified_schema,
    validate_unified_schema,
)


def make_job(
    source="gupy_global",
    source_job_id="1",
    *,
    title="Engineering Intern",
    url="https://example.test/job/1",
):
    return Job(
        source=source,
        source_job_id=source_job_id,
        company="Example",
        title=title,
        location="São Carlos, SP",
        url=url,
        description="Candidates must be pursuing engineering.",
        source_type="official_api",
        latitude=-22.0174,
        longitude=-47.886,
        location_confidence="city",
        detected_intents=["internship"],
        course_scores={
            "chemical_engineering": 91,
            "electrical_engineering": 72,
        },
    )


def test_cp4a_backfills_posting_opportunity_classification_and_lifecycle(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)

        job = make_job()
        store.upsert(job, seen_at="2026-09-20T10:00:00+00:00", commit=False)
        store.conn.execute(
            """
            UPDATE jobs
            SET last_checked_at = ?,
                missing_since = ?,
                miss_count = 1,
                seen_count = 4
            WHERE source = ? AND source_job_id = ?
            """,
            (
                "2026-09-21T10:00:00+00:00",
                "2026-09-21T10:00:00+00:00",
                job.source,
                job.source_job_id,
            ),
        )
        record_discoveries(
            store,
            "successfactors",
            {"tenant:outside"},
            scope_status="out_of_scope",
        )
        finish_scope_run(
            store,
            "gupy_global",
            "global",
            coverage="complete",
        )
        store.commit()

        result = ensure_unified_schema(store)

        assert result["legacy_jobs_scanned"] == 1
        assert result["opportunities"] == 1
        assert result["source_postings"] == 1
        assert result["course_scores"] == 2
        assert result["intents"] == 1

        posting = store.conn.execute(
            "SELECT * FROM source_postings"
        ).fetchone()
        assert posting["source"] == "gupy_global"
        assert posting["source_job_id"] == "1"
        assert posting["miss_count"] == 1
        assert posting["seen_count"] == 4
        assert posting["is_active"] == 1
        assert posting["missing_since"] == "2026-09-21T10:00:00+00:00"

        payload = json.loads(posting["normalized_job_json"])
        assert payload["title"] == "Engineering Intern"
        assert payload["course_scores"]["chemical_engineering"] == 91

        opportunity = store.conn.execute(
            "SELECT * FROM opportunities"
        ).fetchone()
        assert opportunity["company"] == "Example"
        assert opportunity["title"] == "Engineering Intern"
        assert opportunity["location_text"] == "São Carlos, SP"
        assert opportunity["latitude"] == -22.0174
        assert opportunity["longitude"] == -47.886

        scores = {
            row["course_id"]: row["score"]
            for row in store.conn.execute(
                "SELECT course_id, score FROM opportunity_course_scores"
            )
        }
        assert scores == {
            "chemical_engineering": 91,
            "electrical_engineering": 72,
        }

        intents = {
            row["intent_id"]
            for row in store.conn.execute(
                "SELECT intent_id FROM opportunity_intents"
            )
        }
        assert intents == {"internship"}

        assert store.conn.execute(
            "SELECT COUNT(*) FROM discovery_state"
        ).fetchone()[0] == 2
        assert store.conn.execute(
            "SELECT COUNT(*) FROM collection_scopes"
        ).fetchone()[0] == 1

        version = store.conn.execute(
            "SELECT value FROM store_meta WHERE key = 'unified_schema_version'"
        ).fetchone()[0]
        assert version == UNIFIED_SCHEMA_VERSION
        assert validate_unified_schema(store, require_tables=True)["ok"] is True


def test_cp4a_migration_is_idempotent(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        store.upsert(make_job(), commit=True)

        first = ensure_unified_schema(store)
        first_link = store.conn.execute(
            """
            SELECT opportunity_id
            FROM source_postings
            WHERE source = 'gupy_global' AND source_job_id = '1'
            """
        ).fetchone()[0]

        second = ensure_unified_schema(store)
        second_link = store.conn.execute(
            """
            SELECT opportunity_id
            FROM source_postings
            WHERE source = 'gupy_global' AND source_job_id = '1'
            """
        ).fetchone()[0]

        assert first["opportunities"] == second["opportunities"] == 1
        assert first["source_postings"] == second["source_postings"] == 1
        assert first_link == second_link
        assert validate_unified_schema(store, require_tables=True)["ok"] is True


def test_cp4a_shadow_sync_updates_existing_posting_without_changing_identity(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        original = make_job()
        store.upsert(original, commit=True)
        ensure_unified_schema(store)

        opportunity_id = store.conn.execute(
            "SELECT opportunity_id FROM source_postings"
        ).fetchone()[0]

        changed = make_job(title="Chemical Engineering Intern")
        changed.course_scores = {"chemical_engineering": 97}
        changed.detected_intents = ["internship", "summer_internship"]
        store.upsert(changed, commit=True)

        ensure_unified_schema(store)

        posting = store.conn.execute(
            "SELECT opportunity_id FROM source_postings"
        ).fetchone()
        assert posting["opportunity_id"] == opportunity_id

        opportunity = store.conn.execute(
            "SELECT title FROM opportunities WHERE id = ?",
            (opportunity_id,),
        ).fetchone()
        assert opportunity["title"] == "Chemical Engineering Intern"

        scores = store.conn.execute(
            """
            SELECT course_id, score
            FROM opportunity_course_scores
            WHERE opportunity_id = ?
            """,
            (opportunity_id,),
        ).fetchall()
        assert [(row["course_id"], row["score"]) for row in scores] == [
            ("chemical_engineering", 97)
        ]

        intents = {
            row["intent_id"]
            for row in store.conn.execute(
                """
                SELECT intent_id
                FROM opportunity_intents
                WHERE opportunity_id = ?
                """,
                (opportunity_id,),
            )
        }
        assert intents == {"internship", "summer_internship"}


def test_cp4a_does_not_cross_source_merge_during_migration(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        first = make_job(
            source="gupy_global",
            source_job_id="1",
            url="https://example.test/job/123",
        )
        second = make_job(
            source="workday",
            source_job_id="company:123",
            url="https://example.test/job/123",
        )
        store.upsert(first, commit=False)
        store.upsert(second, commit=True)

        result = ensure_unified_schema(store)

        assert result["source_postings"] == 2
        assert result["opportunities"] == 2
        ids = {
            row["opportunity_id"]
            for row in store.conn.execute(
                "SELECT opportunity_id FROM source_postings"
            )
        }
        assert len(ids) == 2


def test_cp4a_preserves_inactive_lifecycle(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        job = make_job()
        store.upsert(job, commit=False)
        store.conn.execute(
            """
            UPDATE jobs
            SET is_active = 0,
                miss_count = 2,
                seen_count = 3,
                missing_since = '2026-09-20T00:00:00+00:00',
                inactive_at = '2026-09-21T00:00:00+00:00',
                last_checked_at = '2026-09-21T00:00:00+00:00'
            WHERE source = ? AND source_job_id = ?
            """,
            (job.source, job.source_job_id),
        )
        store.commit()

        ensure_unified_schema(store)

        posting = store.conn.execute(
            "SELECT * FROM source_postings"
        ).fetchone()
        assert posting["is_active"] == 0
        assert posting["miss_count"] == 2
        assert posting["seen_count"] == 3
        assert posting["inactive_at"] == "2026-09-21T00:00:00+00:00"
        assert validate_unified_schema(store, require_tables=True)["ok"] is True
