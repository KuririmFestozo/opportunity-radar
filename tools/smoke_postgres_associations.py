"""Rollback-only CP5-D cross-source integration smoke against PostgreSQL.

Run from the repository root, with DATABASE_URL set locally:
    python -m tools.smoke_postgres_associations

This test calls the real repository methods but never commits. All fixture
postings, opportunities, scores and intents are reverted in finally.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from models.job import Job
from storage.postgres_repository import PostgresOpportunityRepository
from storage.unified_schema import _stable_opportunity_id


SOURCE_A = "__cp5_smoke_alpha"
SOURCE_B = "__cp5_smoke_beta"
TITLE = "CP5 Engineering Intern Smoke Test"
CONFLICTING_TITLE = "CP5 Different Engineering Role"


def build_fixtures(token: str) -> tuple[Job, Job]:
    """Two source-native postings with identical conservative URL evidence."""
    url = f"https://cp5-smoke.invalid/jobs/{token}"
    shared = {
        "source_job_id": token,
        "company": "CP5 Transactional Smoke Fixture",
        "title": TITLE,
        "location": "São Carlos, SP",
        "url": url,
        "description": "Only a synthetic, rollback-only smoke-test posting.",
        "published_at": "2026-10-01T12:00:00+00:00",
        "employment_type": "internship",
        "workplace_type": "hybrid",
    }
    return (
        Job(
            source=SOURCE_A,
            course_scores={"electrical_engineering": 80},
            detected_intents=["internship"],
            **shared,
        ),
        Job(
            source=SOURCE_B,
            course_scores={
                "electrical_engineering": 95,
                "computer_engineering": 77,
            },
            detected_intents=["internship", "summer_internship"],
            **shared,
        ),
    )


def _postings(conn, token: str) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT source, opportunity_id::text AS opportunity_id,
               association_method
        FROM public.source_postings
        WHERE source IN (%s, %s) AND source_job_id = %s
        """,
        (SOURCE_A, SOURCE_B, token),
    ).fetchall()
    return {str(row["source"]): row for row in rows}


def _classification(conn, opportunity_id: str) -> tuple[dict[str, int], set[str]]:
    scores = {
        str(row["course_id"]): int(row["score"])
        for row in conn.execute(
            """
            SELECT course_id, score FROM public.opportunity_course_scores
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        ).fetchall()
    }
    intents = {
        str(row["intent_id"])
        for row in conn.execute(
            """
            SELECT intent_id FROM public.opportunity_intents
            WHERE opportunity_id = %s
            """,
            (opportunity_id,),
        ).fetchall()
    }
    return scores, intents


def _validate_merge(conn, token: str, anchor_id: str, other_id: str) -> None:
    rows = _postings(conn, token)
    assert set(rows) == {SOURCE_A, SOURCE_B}, rows
    assert {r["opportunity_id"] for r in rows.values()} == {anchor_id}, rows
    assert {r["association_method"] for r in rows.values()} == {
        "conservative_url"
    }, rows
    count = conn.execute(
        """
        SELECT COUNT(*) AS n FROM public.opportunities
        WHERE id IN (%s, %s)
        """,
        (anchor_id, other_id),
    ).fetchone()["n"]
    assert int(count) == 1, f"Merge kept {count} opportunities instead of 1"
    scores, intents = _classification(conn, anchor_id)
    assert scores == {
        "electrical_engineering": 95,
        "computer_engineering": 77,
    }, scores
    assert intents == {"internship", "summer_internship"}, intents


def _validate_split(conn, token: str, first_id: str, second_id: str) -> None:
    rows = _postings(conn, token)
    assert rows[SOURCE_A]["opportunity_id"] == first_id, rows
    assert rows[SOURCE_B]["opportunity_id"] == second_id, rows
    assert {r["association_method"] for r in rows.values()} == {"identity"}, rows
    count = conn.execute(
        """
        SELECT COUNT(*) AS n FROM public.opportunities
        WHERE id IN (%s, %s)
        """,
        (first_id, second_id),
    ).fetchone()["n"]
    assert int(count) == 2, f"Split kept {count} opportunities instead of 2"
    first_scores, first_intents = _classification(conn, first_id)
    second_scores, second_intents = _classification(conn, second_id)
    assert first_scores == {"electrical_engineering": 80}, first_scores
    assert first_intents == {"internship"}, first_intents
    assert second_scores == {
        "electrical_engineering": 95,
        "computer_engineering": 77,
    }, second_scores
    assert second_intents == {"internship", "summer_internship"}, second_intents


def main() -> None:
    token = str(uuid.uuid4())
    first, second = build_fixtures(token)
    first_id = _stable_opportunity_id(first.source, first.source_job_id)
    second_id = _stable_opportunity_id(second.source, second.source_job_id)
    seen_at = datetime.now(timezone.utc)

    print("CP5-D PostgreSQL cross-source smoke (rollback-only)")
    with PostgresOpportunityRepository() as repo:
        conn = repo.conn
        if conn.autocommit:
            raise RuntimeError("Refusing to test with autocommit enabled")

        try:
            conn.execute("SET LOCAL statement_timeout = '120s'")
            conn.execute("SET LOCAL lock_timeout = '10s'")
            repo.upsert_posting(first, seen_at=seen_at.isoformat())
            repo.upsert_posting(
                second, seen_at=(seen_at + timedelta(seconds=1)).isoformat()
            )
            merged = repo.sync_unified_schema(commit=False)
            _validate_merge(conn, token, first_id, second_id)
            print(
                "MERGE OK: 2 fontes -> 1 opportunity; "
                "score máximo e união de intents preservados "
                f"(changes={merged['association_changes']})"
            )

            # Same detail URL but conflicting title must force a safe split.
            second.title = CONFLICTING_TITLE
            repo.upsert_posting(
                second, seen_at=(seen_at + timedelta(seconds=2)).isoformat()
            )
            split = repo.sync_unified_schema(commit=False)
            _validate_split(conn, token, first_id, second_id)
            print(
                "SPLIT OK: conflito de título -> 2 opportunities "
                f"(changes={split['association_changes']})"
            )
        finally:
            # No commit anywhere in this test, even on success.
            conn.rollback()
            print("ROLLBACK executado.")
            leftover = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM public.source_postings
                     WHERE source IN (%s, %s) AND source_job_id = %s)
                        AS postings,
                    (SELECT COUNT(*) FROM public.opportunities
                     WHERE id IN (%s, %s)) AS opportunities
                """,
                (SOURCE_A, SOURCE_B, token, first_id, second_id),
            ).fetchone()
            conn.rollback()
            if int(leftover["postings"]) or int(leftover["opportunities"]):
                raise AssertionError(
                    "Fixture survived ROLLBACK: " + str(dict(leftover))
                )
            print("CLEANUP OK: nenhum registro fictício permaneceu.")

    print("CP5-D smoke: OK")


if __name__ == "__main__":
    main()
