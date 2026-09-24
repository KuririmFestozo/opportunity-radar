"""Controlled CP5 PostgreSQL write smoke test.

Writes one synthetic posting inside a transaction and always rolls it back.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

from models.job import Job
from storage.postgres_repository import PostgresOpportunityRepository
from storage.unified_schema import _stable_opportunity_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-remote-write",
        action="store_true",
        help="Required safety acknowledgement before touching PostgreSQL.",
    )
    return parser.parse_args()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    args = _parse_args()
    if not args.confirm_remote_write:
        print("ABORTADO: use --confirm-remote-write para executar o smoke test.")
        return 2

    if not os.getenv("DATABASE_URL", "").strip():
        print("ABORTADO: DATABASE_URL não configurada.")
        return 2

    token = uuid.uuid4().hex
    source = "cp5_write_smoke"
    source_job_id = f"smoke:{token}"
    opportunity_id = _stable_opportunity_id(source, source_job_id)
    first_seen = _now()
    touched_at = _now()

    job = Job(
        source=source,
        source_job_id=source_job_id,
        company="Opportunity Radar Smoke Test",
        title="CP5 PostgreSQL Write Smoke Test",
        location="São Carlos - SP",
        url=f"https://example.invalid/opportunity-radar/{token}",
        description="Synthetic CP5 write validation. This row must be rolled back.",
        employment_type="Internship",
        workplace_type="hybrid",
        source_type="test",
        latitude=-22.0174,
        longitude=-47.8860,
        location_confidence="city",
        detected_intents=["internship", "summer_internship"],
        course_scores={
            "electrical_engineering": 91,
            "computer_engineering": 67,
        },
        metadata={"cp5_smoke_test": True},
    )

    repository = PostgresOpportunityRepository()

    try:
        print("CP5 PostgreSQL write smoke")
        print(f"Temporary ID: {source_job_id}")
        print("Mode: transactional / rollback-only")
        print()

        before = repository.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM public.source_postings) AS postings,
                (SELECT COUNT(*) FROM public.opportunities) AS opportunities
            """
        ).fetchone()

        prepared, status, needs_processing = repository.prepare_posting(job)
        _assert(status == "new", f"prepare esperado=new, recebido={status}")
        _assert(needs_processing is True, "posting novo deveria exigir processing")
        _assert(
            prepared.source_job_id == source_job_id,
            "prepare alterou identidade",
        )
        print("[OK] prepare_posting -> new")

        repository.upsert_posting(
            job,
            seen_at=first_seen,
            commit=False,
        )

        posting = repository.conn.execute(
            """
            SELECT opportunity_id, is_active
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (source, source_job_id),
        ).fetchone()
        _assert(
            posting is not None,
            "source_postings não recebeu o smoke posting",
        )
        _assert(
            str(posting["opportunity_id"]) == opportunity_id,
            "opportunity_id divergente",
        )
        _assert(bool(posting["is_active"]), "posting não ficou ativo")
        print("[OK] source_postings write")

        opportunity = repository.conn.execute(
            """
            SELECT id, company, title
            FROM public.opportunities
            WHERE id = %s
            """,
            (opportunity_id,),
        ).fetchone()
        _assert(
            opportunity is not None,
            "opportunities não recebeu a opportunity",
        )
        _assert(opportunity["company"] == job.company, "company divergente")
        _assert(opportunity["title"] == job.title, "title divergente")
        print("[OK] opportunities write")

        scores = repository.conn.execute(
            """
            SELECT course_id, score
            FROM public.opportunity_course_scores
            WHERE opportunity_id = %s
            ORDER BY course_id
            """,
            (opportunity_id,),
        ).fetchall()
        score_map = {
            str(row["course_id"]): int(row["score"])
            for row in scores
        }
        _assert(
            score_map == job.course_scores,
            f"course scores divergentes: {score_map}",
        )
        print("[OK] course scores")

        intents = repository.conn.execute(
            """
            SELECT intent_id
            FROM public.opportunity_intents
            WHERE opportunity_id = %s
            ORDER BY intent_id
            """,
            (opportunity_id,),
        ).fetchall()
        intent_values = [str(row["intent_id"]) for row in intents]
        _assert(
            intent_values == sorted(job.detected_intents),
            f"intents divergentes: {intent_values}",
        )
        print("[OK] intents")

        _, status, needs_processing = repository.prepare_posting(job)
        _assert(
            status == "unchanged",
            f"segundo prepare esperado=unchanged, recebido={status}",
        )
        _assert(
            needs_processing is False,
            "posting unchanged não deveria reprocessar",
        )
        print("[OK] prepare_posting -> unchanged")

        repository.touch_posting(
            source,
            source_job_id,
            seen_at=touched_at,
            commit=False,
        )
        touched = repository.conn.execute(
            """
            SELECT is_active
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (source, source_job_id),
        ).fetchone()
        _assert(
            touched is not None and bool(touched["is_active"]),
            "touch falhou",
        )
        print("[OK] touch_posting")

        repository.conn.rollback()
        print("[OK] transaction rollback")

        leftovers = repository.conn.execute(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM public.source_postings
                    WHERE source = %s AND source_job_id = %s
                ) AS postings,
                (
                    SELECT COUNT(*)
                    FROM public.opportunities
                    WHERE id = %s
                ) AS opportunities
            """,
            (source, source_job_id, opportunity_id),
        ).fetchone()
        _assert(
            int(leftovers["postings"]) == 0,
            "rollback deixou source_posting",
        )
        _assert(
            int(leftovers["opportunities"]) == 0,
            "rollback deixou opportunity",
        )

        after = repository.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM public.source_postings) AS postings,
                (SELECT COUNT(*) FROM public.opportunities) AS opportunities
            """
        ).fetchone()
        _assert(
            int(after["postings"]) == int(before["postings"]),
            "contagem de postings mudou",
        )
        _assert(
            int(after["opportunities"]) == int(before["opportunities"]),
            "contagem de opportunities mudou",
        )

        repository.conn.rollback()
        print("[OK] zero resíduos no banco")
        print()
        print("CP5 PostgreSQL write smoke: OK")
        return 0

    except Exception as exc:
        repository.conn.rollback()
        print()
        print(
            "CP5 PostgreSQL write smoke: FALHOU "
            f"({type(exc).__name__}: {exc})"
        )
        return 1

    finally:
        repository.close()


if __name__ == "__main__":
    sys.exit(main())
