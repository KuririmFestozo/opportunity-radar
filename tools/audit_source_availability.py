"""Audit 99jobs, Bettha, Cargill, Cia de Estagios and IEL job links.

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
)


def run(db: Path, *, urls=None, limit=100, apply=False):
    if not db.is_file():
        raise FileNotFoundError(f"Banco SQLite nao encontrado: {db}")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        # Read-only previews must not change user files at all.
        if not apply:
            found = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_availability_checks'"
            ).fetchone()
            if not found:
                # Selection works without writing schema on dry runs by
                # falling back to a temporary in-memory availability table.
                conn.execute("""
                    CREATE TEMP TABLE source_availability_checks (
                      source TEXT,source_job_id TEXT,checked_at TEXT,
                      PRIMARY KEY(source,source_job_id)
                    )
                """)
        else:
            ensure_schema(conn)
        candidates, unmatched = select_postings(conn, urls=urls, limit=limit)
        if unmatched:
            print("[NAO ENCONTRADOS] URLs ausentes do banco escolhido:")
            for item in unmatched:
                print("  " + item)
        print(f"[VERIFICACAO] {len(candidates)} anuncios encontrados | "
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
        stats = Counter()
        for source, job_id, url in candidates:
            verdict, reason = probe(source, url)
            stats[verdict] += 1
            print(f"[{verdict.upper()}] {source}/{job_id} | {reason} | {url}")
            if apply:
                stats["inactivated"] += apply_result(
                    conn, source, job_id, verdict, reason
                )
        if not apply:
            conn.rollback()
        print(
            "[RESUMO] "
            f"{stats['open']} abertas confirmadas | "
            f"{stats['closed']} encerradas | "
            f"{stats['unverified']} inconclusivas | "
            f"{stats['inactivated']} inativadas"
        )
        print("[OK] Dados pessoais preservados; nenhuma vaga apagada.")
        return dict(stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/classroom_latest.db"))
    parser.add_argument("--url", action="append", default=[],
                        help="Link de vaga especifica; pode repetir --url")
    parser.add_argument("--limit", type=int, default=100,
                        help="Numero maximo de anuncios na auditoria geral")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.limit <= 1000:
        parser.error("Use --limit entre 0 e 1000")
    path = args.db.expanduser().resolve()
    try:
        run(path, urls=args.url, limit=args.limit, apply=args.apply)
    except (FileNotFoundError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
