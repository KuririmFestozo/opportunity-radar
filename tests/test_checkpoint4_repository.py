from models.job import Job
from storage.job_store import JobStore
from storage.repository import OpportunityRepository
from storage.sqlite_repository import SQLiteOpportunityRepository


def make_job(source_job_id="tenant:1"):
    return Job(
        source="inhire",
        source_job_id=source_job_id,
        company="Example",
        title="Chemical Engineering Intern",
        location="São Carlos, SP",
        url=f"https://example.test/jobs/{source_job_id}",
        detected_intents=["internship"],
        course_scores={"chemical_engineering": 94},
    )


def test_sqlite_repository_satisfies_repository_contract(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        assert isinstance(repository, OpportunityRepository)
        assert repository.path == tmp_path / "radar.db"
        # SQL connection remains an implementation detail.
        assert not hasattr(repository, "conn")


def test_repository_persists_and_loads_postings(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        job = make_job()
        repository.upsert_posting(job, commit=True)

        assert repository.count_postings() == 1
        assert repository.known_posting_ids("inhire") == {"tenant:1"}

        prepared, status, needs_processing = repository.prepare_posting(job)
        assert status == "unchanged"
        assert needs_processing is False
        assert prepared.title == job.title

        loaded = repository.load_postings()
        assert len(loaded) == 1
        assert loaded[0].source_job_id == "tenant:1"


def test_repository_owns_discovery_and_lifecycle_operations(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        job = make_job()
        repository.upsert_posting(job, commit=False)
        repository.mark_seen_postings([job])
        repository.record_discoveries(
            "successfactors",
            {"tenant:outside"},
            scope_status="out_of_scope",
        )
        repository.commit()

        assert repository.known_discovery_ids(
            "successfactors"
        ) == {"tenant:outside"}

        first = repository.reconcile_scope(
            "inhire",
            set(),
            prefix="tenant:",
            coverage="complete",
            miss_threshold=2,
        )
        repository.commit()
        assert first["new_missing"] == 1
        assert repository.lifecycle_stats()["missing"] == 1

        second = repository.reconcile_scope(
            "inhire",
            set(),
            prefix="tenant:",
            coverage="complete",
            miss_threshold=2,
        )
        repository.commit()
        assert second["inactivated"] == 1
        assert repository.lifecycle_stats()["inactive"] == 1


def test_repository_syncs_cp4a_shadow_schema(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(make_job(), commit=True)
        state = repository.sync_unified_schema()

        assert state["source_postings"] == 1
        assert state["opportunities"] == 1
        assert state["course_scores"] == 1
        assert state["intents"] == 1
        assert state["schema_version"] == "4"


def test_legacy_job_store_remains_available_during_cp4(tmp_path):
    # CP4-B is an abstraction migration, not a flag-day rewrite.
    with JobStore(tmp_path / "legacy.db") as store:
        store.upsert(make_job(), commit=True)
        assert store.count() == 1
