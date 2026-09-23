from models.job import Job
from processing.deduplicate import deduplicate_jobs
from storage.sqlite_repository import SQLiteOpportunityRepository


URL = "https://careers.example.com/jobs/77777"


def make_job(
    source="gupy_global",
    source_job_id="gupy:77777",
    *,
    title="Engineering Intern",
    scores=None,
    intents=None,
):
    return Job(
        source=source,
        source_job_id=source_job_id,
        company="Example Corp",
        title=title,
        location="São Carlos, SP",
        url=URL,
        description="Engineering internship",
        published_at="2026-09-20",
        employment_type="internship",
        workplace_type="hybrid",
        source_type="official_api",
        salary=None,
        latitude=-22.0174,
        longitude=-47.886,
        location_confidence="city",
        course_scores=scores or {"electrical_engineering": 90},
        detected_intents=intents or ["internship"],
    )


def test_cp4e_loads_catalog_directly_from_opportunities(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(make_job(), commit=True)
        repository.sync_unified_schema()

        catalog = repository.load_opportunities()

        assert len(catalog) == 1
        job = catalog[0]
        assert job.company == "Example Corp"
        assert job.title == "Engineering Intern"
        assert job.location == "São Carlos, SP"
        assert job.course_scores == {"electrical_engineering": 90}
        assert job.detected_intents == ["internship"]
        assert job.metadata["catalog_source"] == "relational_opportunities"
        assert job.metadata["classification_source"] == "relational"
        assert job.metadata["source_posting_count"] == 1
        assert job.metadata["opportunity_id"]


def test_cp4e_cross_source_group_becomes_one_catalog_job(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job(
                "gupy_global",
                "gupy:77777",
                scores={"electrical_engineering": 80},
            ),
            seen_at="2026-09-20T10:00:00+00:00",
            commit=False,
        )
        repository.upsert_posting(
            make_job(
                "workday",
                "company:77777",
                scores={
                    "electrical_engineering": 95,
                    "computer_engineering": 89,
                },
                intents=["internship", "summer_internship"],
            ),
            seen_at="2026-09-21T10:00:00+00:00",
            commit=True,
        )
        repository.sync_unified_schema()

        catalog = repository.load_opportunities()

        assert len(catalog) == 1
        job = catalog[0]
        assert job.course_scores == {
            "computer_engineering": 89,
            "electrical_engineering": 95,
        }
        assert job.detected_intents == [
            "internship",
            "summer_internship",
        ]
        assert job.metadata["source_posting_count"] == 2
        assert {
            (ref["source"], ref["source_job_id"])
            for ref in job.metadata["source_references"]
        } == {
            ("gupy_global", "gupy:77777"),
            ("workday", "company:77777"),
        }


def test_cp4e_active_catalog_is_derived_from_posting_lifecycle(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job("gupy_global", "gupy:77777"),
            commit=False,
        )
        repository.upsert_posting(
            make_job("workday", "company:77777"),
            commit=True,
        )
        repository.sync_unified_schema()

        repository._store.conn.execute(
            """
            UPDATE jobs
            SET is_active = 0, miss_count = 2
            WHERE source = 'gupy_global'
            """
        )
        repository.commit()
        repository.sync_unified_schema()
        assert len(repository.load_opportunities(active_only=True)) == 1

        repository._store.conn.execute(
            """
            UPDATE jobs
            SET is_active = 0, miss_count = 2
            WHERE source = 'workday'
            """
        )
        repository.commit()
        repository.sync_unified_schema()

        assert repository.load_opportunities(active_only=True) == []
        assert len(repository.load_opportunities(active_only=False)) == 1


def test_cp4e_relational_catalog_matches_current_dedup_count(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job("gupy_global", "gupy:77777"),
            commit=False,
        )
        repository.upsert_posting(
            make_job("workday", "company:77777"),
            commit=False,
        )
        repository.upsert_posting(
            make_job(
                "smartrecruiters",
                "other:1",
                title="Different Engineering Intern",
            ),
            commit=True,
        )
        repository.sync_unified_schema()

        legacy_catalog = deduplicate_jobs(
            repository._store.load_jobs(active_only=True)
        )
        relational_catalog = repository.load_opportunities(active_only=True)

        assert len(relational_catalog) == len(legacy_catalog) == 2
        assert {
            (job.company, job.title)
            for job in relational_catalog
        } == {
            (job.company, job.title)
            for job in legacy_catalog
        }
