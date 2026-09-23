import json

from models.job import Job
from storage.sqlite_repository import SQLiteOpportunityRepository


URL = "https://careers.example.com/jobs/55555"


def make_job(
    source="gupy_global",
    source_job_id="gupy:55555",
    *,
    scores=None,
    intents=None,
):
    return Job(
        source=source,
        source_job_id=source_job_id,
        company="Example Corp",
        title="Engineering Intern",
        location="São Carlos, SP",
        url=URL,
        description="Engineering internship",
        course_scores=scores or {"electrical_engineering": 82},
        detected_intents=intents or ["internship"],
    )


def test_cp4d_repository_reads_relational_classification(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job(
                scores={"electrical_engineering": 91},
                intents=["internship", "summer_internship"],
            ),
            commit=True,
        )
        repository.sync_unified_schema()

        row = repository._store.conn.execute(
            """
            SELECT job_json
            FROM jobs
            WHERE source = 'gupy_global'
              AND source_job_id = 'gupy:55555'
            """
        ).fetchone()
        payload = json.loads(row["job_json"])
        payload["course_scores"] = {"electrical_engineering": 1}
        payload["detected_intents"] = ["seasonal_job"]
        repository._store.conn.execute(
            """
            UPDATE jobs
            SET job_json = ?
            WHERE source = 'gupy_global'
              AND source_job_id = 'gupy:55555'
            """,
            (json.dumps(payload),),
        )
        repository.commit()

        loaded = repository.load_postings()[0]
        assert loaded.course_scores == {"electrical_engineering": 91}
        assert loaded.detected_intents == [
            "internship",
            "summer_internship",
        ]
        assert loaded.metadata["classification_source"] == "relational"
        assert loaded.metadata["opportunity_id"]


def test_cp4d_associated_postings_share_relational_classification(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job(
                "gupy_global",
                "gupy:55555",
                scores={"electrical_engineering": 80},
                intents=["internship"],
            ),
            seen_at="2026-09-20T10:00:00+00:00",
            commit=False,
        )
        repository.upsert_posting(
            make_job(
                "workday",
                "company:55555",
                scores={
                    "electrical_engineering": 94,
                    "computer_engineering": 89,
                },
                intents=["internship", "summer_internship"],
            ),
            seen_at="2026-09-21T10:00:00+00:00",
            commit=True,
        )
        repository.sync_unified_schema()

        loaded = repository.load_postings()
        expected_scores = {
            "computer_engineering": 89,
            "electrical_engineering": 94,
        }
        expected_intents = ["internship", "summer_internship"]

        assert len(loaded) == 2
        for job in loaded:
            assert job.course_scores == expected_scores
            assert job.detected_intents == expected_intents
            assert job.metadata["classification_source"] == "relational"

        assert len(
            {job.metadata["opportunity_id"] for job in loaded}
        ) == 1


def test_cp4d_records_classification_contract_version(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(make_job(), commit=True)
        state = repository.sync_unified_schema()

        row = repository._store.conn.execute(
            """
            SELECT value
            FROM store_meta
            WHERE key = 'unified_classification_version'
            """
        ).fetchone()

        assert state["classification_version"] == "1"
        assert row["value"] == "1"
