"""Audit the availability of job links from ALL configured source families.

Run from the repository root after stopping Spring Boot:
  python -m tools.audit_source_availability --db data/classroom_latest.db --limit 100
  python -m tools.audit_source_availability --db data/classroom_latest.db --limit 100 --apply
  python -m tools.audit_source_availability --db data/classroom_latest.db --url "https://..." --apply

Without --apply: network preview; no local database changes. With --apply:
back up the SQLite and record open/closed/unverified per posting.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from processing.source_availability import (
    apply_result, ensure_schema, probe, select_postings,
    source_coverage, SUPPORTED,
)


def run(db: Path, *, urls=None, limit=100, apply=False,
        confirm_closed_urls=None, flag_unavailable_urls=None):
    """Audit pages or apply explicit user-confirmed status for exact links.

    Manual confirmation never requests a website. It only updates existing
    source_postings matched to the provided URL and creates a SQLite backup.
    """
    if not db.is_file():
        raise FileNotFoundError(f"Banco SQLite nao encontrado: {db}")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        # Read-only previews do not create any SQLite tables.
        rows = source_coverage(conn)
        print(f"[FONTES] {len(rows)} fontes presentes no banco, "
              f"{len(SUPPORTED)} familias conhecidas pelo codigo.")
        for row in rows:
            supported = "OK" if row["source"] in SUPPORTED else "SEM VERIFICADOR"
            print(f'  {row["source"]}: {row["historical"]} historicas, '
                  f'{row["active"]} ativas, '
                  f'{row["verified_open"]} abertas confirmadas, '
                  f'{row["verified_closed"]} encerradas, '
                  f'{row["unverified"]} inconclusivas, '
                  f'{row["unchecked"]} nao verificadas [{supported}]')
        closed_urls = list(confirm_closed_urls or [])
        unavailable_urls = list(flag_unavailable_urls or [])
        manual = bool(closed_urls or unavailable_urls)
        if manual and not apply:
            raise ValueError("Confirmacao manual requer --apply")
        if manual and urls:
            raise ValueError("Nao misture --url com confirmacoes manuais")
        closed_keys, unavailable_keys = set(), set()
        if manual:
            closed_rows, _ = select_postings(conn, urls=closed_urls, limit=0) if closed_urls else ([], [])
            unavailable_rows, _ = select_postings(conn, urls=unavailable_urls, limit=0) if unavailable_urls else ([], [])
            closed_keys = {(row[0], str(row[1])) for row in closed_rows}
            unavailable_keys = {(row[0], str(row[1])) for row in unavailable_rows}
            overlap = closed_keys & unavailable_keys
            if overlap:
                raise ValueError(f"Links com classificacoes contraditorias: {sorted(overlap)}")
        wanted_urls = closed_urls + unavailable_urls if manual else urls
        candidates, unmatched = select_postings(conn, urls=wanted_urls, limit=limit)
        if unmatched:
            print("[NAO ENCONTRADOS] URLs ausentes do banco escolhido:")
            for item in unmatched:
                print("  " + item)
        print(f"[VERIFICACAO] {len(candidates)} anuncios de "
              f"{len({row[0] for row in candidates})} fontes | "
              f"{'APLICAR' if apply else 'PREVIA'}")
        if apply and candidates:
            backups = db.parent / "backups"
            backups.mkdir(exist_ok=True)
            backup = backups / (
                f"{db.stem}-before-availability-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                + ".db"
            )
            with sqlite3.connect(backup) as saved:
                conn.backup(saved)
            print(f"[BACKUP] {backup}")
            ensure_schema(conn)
        stats = Counter()
        by_source = {}
        for source, job_id, url in candidates:
            if manual:
                if (source, str(job_id)) in closed_keys:
                    verdict, reason = "closed", "user_confirmed_applications_closed"
                elif (source, str(job_id)) in unavailable_keys:
                    verdict, reason = "unverified", "user_reported_unavailable_link"
                else:
                    raise ValueError(f"Anuncio nao classificado: {source}/{job_id}")
            else:
                verdict, reason = probe(source, url)
            stats[verdict] += 1
            by_source.setdefault(source, Counter())[verdict] += 1
            print(f"[{verdict.upper()}] {source}/{job_id} | {reason} | {url}")
            if apply:
                stats["inactivated"] += apply_result(
                    conn, source, job_id, verdict, reason
                )
        if not apply:
            conn.rollback()
        print("[RESULTADOS POR FONTE]")
        for source, result in sorted(by_source.items()):
            print(f"  {source}: {result['open']} abertas, "
                  f"{result['closed']} encerradas, "
                  f"{result['unverified']} inconclusivas")
        print(
            "[RESUMO] "
            f"{stats['open']} abertas confirmadas | "
            f"{stats['closed']} encerradas | "
            f"{stats['unverified']} inconclusivas | "
            f"{stats['inactivated']} inativadas"
        )
        print("[OK] Dados pessoais preservados; nenhuma vaga apagada.")
        return {
            "open": stats["open"], "closed": stats["closed"],
            "unverified": stats["unverified"],
            "inactivated": stats["inactivated"],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/classroom_latest.db"))
    parser.add_argument("--url", action="append", default=[],
                        help="Link de vaga especifica; pode repetir --url")
    parser.add_argument("--confirm-closed-url", action="append", default=[],
                        help="Confirmacao MANUAL de inscricoes encerradas; repetivel, exige --apply")
    parser.add_argument("--flag-unavailable-url", action="append", default=[],
                        help="Marcar link indisponivel/inconclusivo, sem afirmar encerramento; exige --apply")
    parser.add_argument("--limit", type=int, default=100,
                        help="Numero maximo de anuncios na auditoria geral")
    parser.add_argument("--report", action="store_true",
                        help="Exibir totais por fonte sem acessar sites")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.limit <= 1000:
        parser.error("Use --limit entre 0 e 1000")
    if (args.confirm_closed_url or args.flag_unavailable_url) and (
        not args.apply or args.report or args.url
    ):
        parser.error("Confirme com --apply, sem --report nem --url, ao usar confirmacoes manuais.")
    path = args.db.expanduser().resolve()
    try:
        run(path, urls=args.url,
            limit=0 if args.report else args.limit,
            apply=args.apply and not args.report,
            confirm_closed_urls=args.confirm_closed_url,
            flag_unavailable_urls=args.flag_unavailable_url)
    except (FileNotFoundError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
