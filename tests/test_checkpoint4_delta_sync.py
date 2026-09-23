from models.job import Job
from storage.sqlite_repository import SQLiteOpportunityRepository


def make_job(source="gupy_global", source_job_id="gupy:1"):
    return Job(
        source=source,
        source_job_id=source_job_id,
        company="Example",
        title="Engineering Intern",
        location="São Carlos, SP",
        url="https://example.test/jobs/12345",
        description="Internship",
        detected_intents=["internship"],
        course_scores={"electrical_engineering": 90},
    )


def test_cp4c_second_sync_is_delta_only(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(make_job(), commit=True)

        first = repository.sync_unified_schema()
        second = repository.sync_unified_schema()

        assert first["source_postings"] == 1
        assert second["posting_rows_synced"] == 0
        assert second["association_changes"] == 0
        assert second["opportunities_rebuilt"] == 0


def test_cp4c_only_changed_content_rebuilds_affected_opportunity(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(make_job(), commit=True)
        repository.sync_unified_schema()

        changed = make_job()
        changed.description = "Updated internship"
        repository.upsert_posting(changed, commit=True)

        state = repository.sync_unified_schema()

        assert state["posting_rows_synced"] == 1
        assert state["association_changes"] == 0
        assert state["opportunities_rebuilt"] == 1
