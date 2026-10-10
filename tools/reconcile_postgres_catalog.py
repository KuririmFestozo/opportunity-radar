"""Plan or apply CP5 PostgreSQL catalog associations without collecting jobs.

Read-only preview (default):
    python -m tools.reconcile_postgres_catalog

Apply only after reviewing preview and checking the posting count:
    python -m tools.reconcile_postgres_catalog --apply --expected-postings 33062

Requires DATABASE_URL. Does not run collectors or backfill job content.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from storage.postgres_repository import (
    PostgresOpportunityRepository,
    _association_plan,
)


_ROWS_SQL = """
    SELECT
        source, source_job_id, opportunity_id,
        association_method, normalized_job_json,
        first_seen_at, last_changed_at
    FROM public.source_postings
    ORDER BY source, source_job_id
"""


def summarize_plan(
    rows: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    current_opportunities: int,
) -> dict[str, Any]:
    groups = plan["groups"]
    links = plan["link_updates"]
    group_sources = [
        {job.source for job in group}
        for group in groups
    ]
    methods = Counter(
        str(row.get("association_method") or "identity")
        for row in rows
    )
    return {
        "source_postings": len(rows),
        "opportunities_before": current_opportunities,
        "opportunities_expected": len(groups),
        "cross_source_groups_expected": sum(
            len(sources) > 1 for sources in group_sources
        ),
        "association_changes": len(links),
        "opportunities_to_rebuild": sum(
            key in plan["groups_by_opportunity"]
            for key in plan["affected_opportunity_ids"]
        ),
        "orphan_or_redundant_opportunities": (
            current_opportunities - len(groups)
        ),
        "association_methods_before": dict(sorted(methods.items())),
        "changed_source_sample": [
            {"source": source, "source_job_id": source_job_id, "method": method}
            for _, method, source, source_job_id in links[:8]
        ],
    }


def guard_apply(
    report: dict[str, Any],
    *,
    expected_postings: int | None,
    max_changes: int,
) -> None:
    if expected_postings is None:
        raise ValueError(
            "--apply exige --expected-postings para evitar "
            "reconciliacao sobre dados alterados."
        )
    if int(report["source_postings"]) != expected_postings:
        raise ValueError(
            f"Quantidade de postings mudou: esperado {expected_postings}, "
            f"encontrado {report['source_postings']}. Rode o dry-run novamente."
        )
    if report["orphan_or_redundant_opportunities"] < 0:
        raise ValueError("Catalogo inconsistente: faltam opportunities.")
    if report["association_changes"] > max_changes:
        raise ValueError(
            f"{report['association_changes']} associacoes mudariam; "
            f"limite de seguranca = {max_changes}. Revise o dry-run."
        )


def verify_associations(
    conn: Any,
    expected: dict[tuple[str, str], tuple[str, str]],
) -> None:
    rows = conn.execute(
        """
        SELECT source, source_job_id, opportunity_id::text AS opportunity_id,
               association_method
        FROM public.source_postings
        """
    ).fetchall()
    actual = {
        (str(row["source"]), str(row["source_job_id"])): (
            str(row["opportunity_id"]),
            str(row["association_method"] or "identity"),
        )
        for row in rows
    }
    if actual != expected:
        differences = sum(
            actual.get(key) != value for key, value in expected.items()
        )
        differences += len(set(actual) - set(expected))
        raise RuntimeError(
            f"Associacoes apos reconciliacao divergem em {differences} postings."
        )


def run(
    *,
    apply: bool = False,
    expected_postings: int | None = None,
    max_changes: int = 100,
) -> dict[str, Any]:
    with PostgresOpportunityRepository() as repo:
        conn = repo.conn
        if conn.autocommit:
            raise RuntimeError("Conexao autocommit nao e segura para reconciliar.")

        try:
            # Keep the same catalog snapshot across planning and validation.
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            conn.execute("SET LOCAL statement_timeout = '180s'")
            conn.execute("SET LOCAL lock_timeout = '10s'")
            if not apply:
                conn.execute("SET TRANSACTION READ ONLY")

            rows = conn.execute(_ROWS_SQL).fetchall()
            initial_opportunities = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM public.opportunities"
                ).fetchone()["n"]
            )
            plan = _association_plan(rows)
            report = summarize_plan(
                rows,
                plan,
                current_opportunities=initial_opportunities,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))

            if not apply:
                print("DRY-RUN OK: nenhuma alteracao foi aplicada.")
                return report

            guard_apply(
                report,
                expected_postings=expected_postings,
                max_changes=max_changes,
            )
            if not plan["affected_opportunity_ids"] and (
                report["orphan_or_redundant_opportunities"] == 0
            ):
                print("SEM ALTERACOES: catalogo ja esta reconciliado.")
                return report

            updated = repo.sync_unified_schema(commit=False)
            if updated["association_changes"] != report["association_changes"]:
                raise RuntimeError("O plano mudou entre a previa e a execucao.")
            if updated["source_postings"] != report["source_postings"]:
                raise RuntimeError("Quantidade de postings mudou durante o ajuste.")
            if updated["opportunities"] != report["opportunities_expected"]:
                raise RuntimeError("Quantidade final de opportunities inesperada.")
            verify_associations(conn, plan["desired_by_key"])
            conn.commit()
            print("APLICADO: associacoes conferidas e transacao confirmada.")
            return report
        except Exception:
            conn.rollback()
            raise
        finally:
            # Dry-run and no-op apply always close with ROLLBACK.
            # After a successful COMMIT this is harmless.
            conn.rollback()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Grava mudancas; sem esta opcao o comando e somente leitura.",
    )
    parser.add_argument(
        "--expected-postings",
        type=int,
        help="Quantidade de postings observada no dry-run (obrigatoria para apply).",
    )
    parser.add_argument(
        "--max-changes",
        type=int,
        default=100,
        help="Limite de associacoes alteradas em um apply (padrao: 100).",
    )
    args = parser.parse_args()
    if args.max_changes < 0:
        parser.error("--max-changes nao pode ser negativo.")
    run(
        apply=args.apply,
        expected_postings=args.expected_postings,
        max_changes=args.max_changes,
    )


if __name__ == "__main__":
    main()
