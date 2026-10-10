"""Controlled CP5 PostgreSQL discovery/lifecycle smoke test.

Creates one synthetic posting and exercises discovery state, lifecycle
reconciliation and collection scopes inside a transaction. The transaction is
always rolled back, so the remote database should be unchanged afterwards.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from models.job import Job
from storage.postgres_repository import PostgresOpportunityRepository
from storage.unified_schema import _stable_opportunity_id


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


def _iso(base: datetime, seconds: int) -> str:
    return (base + timedelta(seconds=seconds)).isoformat()


def main() -> int:
    args = _parse_args()
    if not args.confirm_remote_write:
        print("ABORTADO: use --confirm-remote-write para executar o smoke test.")
        return 2

    if not os.getenv("DATABASE_URL", "").strip():
        print("ABORTADO: DATABASE_URL não configurada.")
        return 2

    token = uuid.uuid4().hex
    source = "cp5_lifecycle_smoke"
    source_job_id = f"smoke:{token}"
    scope_key = f"scope:{token}"
    opportunity_id = _stable_opportunity_id(source, source_job_id)
    base = datetime.now(timezone.utc)

    job = Job(
        source=source,
        source_job_id=source_job_id,
        company="Opportunity Radar Lifecycle Smoke Test",
        title="CP5 Lifecycle Smoke Test",
        location="São Carlos - SP",
        url=f"https://example.invalid/opportunity-radar/lifecycle/{token}",
        description="Synthetic CP5 lifecycle validation. This row must be rolled back.",
        source_type="test",
        detected_intents=["internship"],
        course_scores={"electrical_engineering": 80},
        metadata={"cp5_lifecycle_smoke_test": True},
    )

    repository = PostgresOpportunityRepository()

    try:
        print("CP5 PostgreSQL discovery/lifecycle smoke")
        print(f"Temporary ID: {source_job_id}")
        print(f"Temporary scope: {scope_key}")
        print("Mode: transactional / rollback-only")
        print()

        before = repository.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM public.source_postings) AS postings,
                (SELECT COUNT(*) FROM public.opportunities) AS opportunities,
                (SELECT COUNT(*) FROM public.discovery_state) AS discoveries,
                (SELECT COUNT(*) FROM public.collection_scopes) AS scopes
            """
        ).fetchone()

        repository.upsert_posting(
            job,
            seen_at=_iso(base, 0),
            commit=False,
        )
        print("[OK] synthetic posting created")

        recorded = repository.record_discoveries(
            source,
            [source_job_id, source_job_id],
            scope_status="catalog",
            seen_at=_iso(base, 1),
        )
        _assert(recorded == 1, f"record_discoveries esperado=1, recebido={recorded}")

        discovery = repository.conn.execute(
            """
            SELECT scope_status, seen_count
            FROM public.discovery_state
            WHERE source = %s AND source_job_id = %s
            """,
            (source, source_job_id),
        ).fetchone()
        _assert(discovery is not None, "discovery_state não recebeu o ID")
        _assert(discovery["scope_status"] == "catalog", "scope_status divergente")
        _assert(int(discovery["seen_count"]) == 1, "seen_count inicial divergente")
        print("[OK] record_discoveries")

        seen = repository.mark_seen_ids(
            source,
            [source_job_id],
            seen_at=_iso(base, 2),
        )
        _assert(seen == {"seen": 1, "reopened": 0}, f"mark_seen inicial divergente: {seen}")

        posting = repository.conn.execute(
            """
            SELECT is_active, miss_count, missing_since, inactive_at, seen_count
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (source, source_job_id),
        ).fetchone()
        _assert(posting is not None, "posting desapareceu após mark_seen")
        _assert(bool(posting["is_active"]), "posting deveria estar ativo")
        _assert(int(posting["miss_count"]) == 0, "miss_count deveria estar zerado")
        _assert(posting["missing_since"] is None, "missing_since deveria estar NULL")
        _assert(posting["inactive_at"] is None, "inactive_at deveria estar NULL")
        _assert(int(posting["seen_count"]) == 1, "seen_count do posting deveria ser 1")
        print("[OK] mark_seen_ids")

        partial = repository.reconcile_scope(
            source,
            [],
            coverage="partial",
            miss_threshold=2,
            checked_at=_iso(base, 3),
        )
        _assert(partial["skipped"] is True, f"partial deveria ser skipped: {partial}")

        posting = repository.conn.execute(
            """
            SELECT miss_count, is_active
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (source, source_job_id),
        ).fetchone()
        _assert(int(posting["miss_count"]) == 0, "partial alterou miss_count")
        _assert(bool(posting["is_active"]), "partial alterou is_active")
        print("[OK] partial reconciliation is conservative")

        first_miss = repository.reconcile_scope(
            source,
            [],
            coverage="complete",
            miss_threshold=2,
            checked_at=_iso(base, 4),
        )
        _assert(first_miss["skipped"] is False, f"complete marcado como skipped: {first_miss}")
        _assert(first_miss["checked"] == 1, f"checked esperado=1: {first_miss}")
        _assert(first_miss["new_missing"] == 1, f"new_missing esperado=1: {first_miss}")
        _assert(first_miss["inactivated"] == 0, f"inactivated esperado=0: {first_miss}")

        posting = repository.conn.execute(
            """
            SELECT miss_count, is_active, missing_since, inactive_at
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (source, source_job_id),
        ).fetchone()
        _assert(int(posting["miss_count"]) == 1, "primeira ausência deveria gerar miss_count=1")
        _assert(bool(posting["is_active"]), "primeira ausência não deveria inativar")
        _assert(posting["missing_since"] is not None, "missing_since deveria ser preenchido")
        _assert(posting["inactive_at"] is None, "inactive_at ainda deveria estar NULL")
        print("[OK] first complete miss stays active")

        repository.finish_scope_run(
            source,
            scope_key,
            coverage="partial",
            finished_at=_iso(base, 5),
        )
        _assert(
            repository.needs_full_audit(source, scope_key, every_runs=2) is True,
            "uma partial run deveria pedir full audit com every_runs=2",
        )

        repository.finish_scope_run(
            source,
            scope_key,
            coverage="complete",
            finished_at=_iso(base, 6),
        )
        scope = repository.conn.execute(
            """
            SELECT successful_runs, last_full_run, last_coverage
            FROM public.collection_scopes
            WHERE source = %s AND scope_key = %s
            """,
            (source, scope_key),
        ).fetchone()
        _assert(scope is not None, "collection_scopes não recebeu o scope")
        _assert(int(scope["successful_runs"]) == 2, "successful_runs esperado=2")
        _assert(int(scope["last_full_run"]) == 2, "last_full_run esperado=2")
        _assert(scope["last_coverage"] == "complete", "last_coverage esperado=complete")
        _assert(
            repository.needs_full_audit(source, scope_key, every_runs=2) is False,
            "full run deveria resetar a necessidade de audit",
        )
        print("[OK] collection scope counters / audit cadence")

        second_miss = repository.reconcile_scope(
            source,
            [],
            coverage="complete",
            miss_threshold=2,
            checked_at=_iso(base, 7),
        )
        _assert(second_miss["new_missing"] == 0, f"segunda ausência não é new_missing: {second_miss}")
        _assert(second_miss["inactivated"] == 1, f"segunda ausência deveria inativar: {second_miss}")

        posting = repository.conn.execute(
            """
            SELECT miss_count, is_active, missing_since, inactive_at
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (source, source_job_id),
        ).fetchone()
        _assert(int(posting["miss_count"]) == 2, "segunda ausência deveria gerar miss_count=2")
        _assert(not bool(posting["is_active"]), "posting deveria estar inativo")
        _assert(posting["inactive_at"] is not None, "inactive_at deveria ser preenchido")
        print("[OK] second complete miss inactivates")

        reopened = repository.mark_seen_ids(
            source,
            [source_job_id],
            seen_at=_iso(base, 8),
        )
        _assert(reopened == {"seen": 1, "reopened": 1}, f"reopen divergente: {reopened}")

        posting = repository.conn.execute(
            """
            SELECT miss_count, is_active, missing_since, inactive_at
            FROM public.source_postings
            WHERE source = %s AND source_job_id = %s
            """,
            (source, source_job_id),
        ).fetchone()
        _assert(int(posting["miss_count"]) == 0, "reopen deveria zerar miss_count")
        _assert(bool(posting["is_active"]), "reopen deveria reativar posting")
        _assert(posting["missing_since"] is None, "reopen deveria limpar missing_since")
        _assert(posting["inactive_at"] is None, "reopen deveria limpar inactive_at")
        print("[OK] observed posting reopens cleanly")

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
                ) AS opportunities,
                (
                    SELECT COUNT(*)
                    FROM public.discovery_state
                    WHERE source = %s AND source_job_id = %s
                ) AS discoveries,
                (
                    SELECT COUNT(*)
                    FROM public.collection_scopes
                    WHERE source = %s AND scope_key = %s
                ) AS scopes
            """,
            (
                source,
                source_job_id,
                opportunity_id,
                source,
                source_job_id,
                source,
                scope_key,
            ),
        ).fetchone()
        _assert(int(leftovers["postings"]) == 0, "rollback deixou source_posting")
        _assert(int(leftovers["opportunities"]) == 0, "rollback deixou opportunity")
        _assert(int(leftovers["discoveries"]) == 0, "rollback deixou discovery_state")
        _assert(int(leftovers["scopes"]) == 0, "rollback deixou collection_scope")

        after = repository.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM public.source_postings) AS postings,
                (SELECT COUNT(*) FROM public.opportunities) AS opportunities,
                (SELECT COUNT(*) FROM public.discovery_state) AS discoveries,
                (SELECT COUNT(*) FROM public.collection_scopes) AS scopes
            """
        ).fetchone()

        for key in ("postings", "opportunities", "discoveries", "scopes"):
            _assert(
                int(after[key]) == int(before[key]),
                f"contagem global mudou após rollback: {key}",
            )

        repository.conn.rollback()
        print("[OK] zero resíduos no banco")
        print()
        print("CP5 PostgreSQL discovery/lifecycle smoke: OK")
        return 0

    except Exception as exc:
        repository.conn.rollback()
        print()
        print(
            "CP5 PostgreSQL discovery/lifecycle smoke: FALHOU "
            f"({type(exc).__name__}: {exc})"
        )
        return 1

    finally:
        repository.close()


if __name__ == "__main__":
    sys.exit(main())
