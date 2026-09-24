from pathlib import Path

import pytest

from models.job import Job
from storage.postgres_repository import PostgresOpportunityRepository
from storage.sqlite_repository import SQLiteOpportunityRepository
from tools.migrate_sqlite_to_postgres import _prepare_sqlite, _snapshot


def test_cp5_sqlite_snapshot_preserves_relational_catalog(tmp_path):
    db = tmp_path / "radar.db"
    job = Job(
        source="test",
        source_job_id="job-1",
        company="Example",
        title="Estágio em Engenharia",
        location="São Carlos - SP",
        url="https://example.com/jobs/1",
        description="Vaga de estágio.",
        detected_intents=["internship"],
        course_scores={"electrical_engineering": 90},
    )

    with SQLiteOpportunityRepository(db) as repo:
        repo.upsert_posting(job)
        repo.commit()
        state = repo.sync_unified_schema()
        assert state["source_postings"] == 1
        assert state["opportunities"] == 1

    _prepare_sqlite(db)
    data = _snapshot(db)

    assert len(data["source_postings"]) == 1
    assert len(data["opportunities"]) == 1
    assert data["source_postings"][0]["source"] == "test"
    assert data["source_postings"][0]["source_job_id"] == "job-1"
    assert data["opportunity_intents"][0]["intent_id"] == "internship"
    assert data["opportunity_course_scores"][0]["score"] == 90


def test_cp5_postgres_repository_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        PostgresOpportunityRepository("")


def test_cp5_schema_uses_postgis_and_source_native_identity():
    schema = Path("database/schema.sql").read_text(encoding="utf-8").lower()

    assert "create extension if not exists postgis with schema extensions" in schema
    assert "extensions.geography(point, 4326)" in schema
    assert "primary key(source, source_job_id)" in schema
    assert "enable row level security" in schema
    assert "st_dwithin" in schema
