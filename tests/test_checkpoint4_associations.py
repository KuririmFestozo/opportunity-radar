from models.job import Job
from storage.sqlite_repository import SQLiteOpportunityRepository
from storage.unified_schema import validate_unified_schema


URL = "https://careers.example.com/jobs/12345"


def make_job(
    source,
    source_job_id,
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
        detected_intents=intents or ["internship"],
        course_scores=scores or {"electrical_engineering": 80},
    )


def links(repository):
    return repository._store.conn.execute(
        """
        SELECT source, source_job_id, opportunity_id, association_method
        FROM source_postings
        ORDER BY source, source_job_id
        """
    ).fetchall()


def test_cp4c_persists_cross_source_association_and_combines_classification(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job(
                "gupy_global",
                "gupy:123",
                scores={"electrical_engineering": 80},
            ),
            seen_at="2026-09-20T10:00:00+00:00",
            commit=False,
        )
        repository.upsert_posting(
            make_job(
                "workday",
                "company:123",
                scores={
                    "electrical_engineering": 92,
                    "computer_engineering": 88,
                },
                intents=["internship", "summer_internship"],
            ),
            seen_at="2026-09-21T10:00:00+00:00",
            commit=True,
        )

        state = repository.sync_unified_schema()
        rows = links(repository)

        assert state["source_postings"] == 2
        assert state["opportunities"] == 1
        assert state["active_opportunities"] == 1
        assert state["cross_source_opportunities"] == 1
        assert len({row["opportunity_id"] for row in rows}) == 1
        assert {row["association_method"] for row in rows} == {
            "conservative_url"
        }

        opportunity_id = rows[0]["opportunity_id"]
        scores = {
            row["course_id"]: row["score"]
            for row in repository._store.conn.execute(
                """
                SELECT course_id, score
                FROM opportunity_course_scores
                WHERE opportunity_id = ?
                """,
                (opportunity_id,),
            )
        }
        assert scores == {
            "computer_engineering": 88,
            "electrical_engineering": 92,
        }
        intents = {
            row["intent_id"]
            for row in repository._store.conn.execute(
                """
                SELECT intent_id
                FROM opportunity_intents
                WHERE opportunity_id = ?
                """,
                (opportunity_id,),
            )
        }
        assert intents == {"internship", "summer_internship"}
        assert validate_unified_schema(
            repository._store,
            require_tables=True,
        )["ok"] is True


def test_cp4c_keeps_opportunity_id_when_new_source_appears(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job("gupy_global", "gupy:123"),
            seen_at="2026-09-19T10:00:00+00:00",
            commit=False,
        )
        repository.upsert_posting(
            make_job("workday", "company:123"),
            seen_at="2026-09-20T10:00:00+00:00",
            commit=True,
        )
        repository.sync_unified_schema()
        original_id = links(repository)[0]["opportunity_id"]

        repository.upsert_posting(
            make_job("smartrecruiters", "company-123"),
            seen_at="2026-09-21T10:00:00+00:00",
            commit=True,
        )
        state = repository.sync_unified_schema()

        assert state["opportunities"] == 1
        assert {row["opportunity_id"] for row in links(repository)} == {
            original_id
        }


def test_cp4c_can_split_previous_association_when_data_diverges(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job("gupy_global", "gupy:123"),
            seen_at="2026-09-19T10:00:00+00:00",
            commit=False,
        )
        repository.upsert_posting(
            make_job("workday", "company:123"),
            seen_at="2026-09-20T10:00:00+00:00",
            commit=True,
        )
        assert repository.sync_unified_schema()["opportunities"] == 1

        repository.upsert_posting(
            make_job(
                "workday",
                "company:123",
                title="Senior Engineering Manager",
            ),
            seen_at="2026-09-21T10:00:00+00:00",
            commit=True,
        )
        state = repository.sync_unified_schema()
        rows = links(repository)

        assert state["opportunities"] == 2
        assert state["cross_source_opportunities"] == 0
        assert len({row["opportunity_id"] for row in rows}) == 2
        assert {row["association_method"] for row in rows} == {"identity"}


def test_cp4c_opportunity_stays_active_while_any_posting_is_active(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repository:
        repository.upsert_posting(
            make_job("gupy_global", "gupy:123"),
            commit=False,
        )
        repository.upsert_posting(
            make_job("workday", "company:123"),
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
        assert repository.sync_unified_schema()["active_opportunities"] == 1

        repository._store.conn.execute(
            """
            UPDATE jobs
            SET is_active = 0, miss_count = 2
            WHERE source = 'workday'
            """
        )
        repository.commit()
        state = repository.sync_unified_schema()

        assert state["opportunities"] == 1
        assert state["active_opportunities"] == 0
