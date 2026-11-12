"""Inspect or run conservative vacancy retirement against an existing SQLite.

PowerShell, with Spring Boot stopped:
    python -m tools.retirement_cleanup --db web-mvc/radar-web.db --report
    python -m tools.retirement_cleanup --db web-mvc/radar-web.db --apply

Only confirmed closed or repeatedly missing official vacancy URLs qualify.
Deletion requires five bad checks on separate UTC dates spanning >=14 days;
the database is backed up immediately before any physical deletion.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from processing.retirement import _eligible, _exists, run_daily_retirement


def report(db: Path):
    if not db.is_file():
        raise FileNotFoundError(db)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA query_only=ON")
        present = _exists(conn, "posting_retirement_checks")
        tracked = conn.execute(
            "SELECT COUNT(*) FROM posting_retirement_checks"
        ).fetchone()[0] if present else 0
        due = []
        if present and _exists(conn, "purged_postings"):
            from datetime import datetime, timezone
            day = datetime.now(timezone.utc).date().isoformat()
            due = _eligible(conn, day, max_items=100000)
        print(f"[RELATORIO] {tracked} anuncios em acompanhamento; "
              f"{len(due)} elegiveis para exclusao condicionada.")
        print("[SEGURO] Consulta sem modificacoes e sem acesso aos sites.")
        return {"tracked": tracked, "ready": len(due)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/opportunity_radar.db"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", action="store_true", help="So consulta, sem alteracoes")
    mode.add_argument("--apply", action="store_true", help="Rever links e aplicar politica")
    parser.add_argument("--recheck-limit", type=int, default=120)
    parser.add_argument("--delete-limit", type=int, default=30)
    args = parser.parse_args()
    db = args.db.expanduser().resolve()
    if not db.is_file():
        parser.error(f"Arquivo inexistente: {db}")
    if args.report:
        report(db)
        return 0
    try:
        with sqlite3.connect(db) as conn:
            result = run_daily_retirement(
                conn, db_path=db, recheck_limit=args.recheck_limit,
                delete_limit=args.delete_limit,
            )
        print("[LIMPEZA] " + " | ".join(f"{k}={v}" for k, v in result.items()))
    except (ValueError, sqlite3.DatabaseError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
