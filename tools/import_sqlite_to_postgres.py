"""Optional, local-only migration of a *stopped* website's SQLite catalog to PostgreSQL.

Requires: pip install psycopg2-binary
Set PG_DSN environment variable; never put credentials in the repository.
Usage: python tools/import_sqlite_to_postgres.py --from-db web-mvc/radar-web.db
       python tools/import_sqlite_to_postgres.py --from-db web-mvc/radar-web.db --include-users
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys

from psycopg2 import connect
from psycopg2.extras import execute_values

# Strict allowlist: table and column identifiers are not accepted from command-line input.
TABLES = [
    ("opportunities", ("id", "company", "title", "description", "location_text",
                       "workplace_type", "employment_type", "published_at", "canonical_url",
                       "updated_at", "latitude", "longitude"), ("id",)),
    ("source_postings", ("source", "source_job_id", "opportunity_id", "is_active",
                         "url", "last_seen_at"), ("source", "source_job_id")),
    ("opportunity_course_scores", ("opportunity_id", "course_id", "score"),
                                  ("opportunity_id", "course_id")),
    ("opportunity_intents", ("opportunity_id", "intent_id"),
                            ("opportunity_id", "intent_id")),
    ("source_availability_checks", ("source", "source_job_id", "verdict",
                                    "evidence", "checked_at"), ("source", "source_job_id")),
]
PERSONAL_TABLES = [
    ("web_users", ("id", "username", "password_hash", "created_at"), ("id",)),
    ("web_device_favorites", ("id", "owner_id", "opportunity_id", "created_at"), ("id",)),
    ("web_device_applications", ("id", "owner_id", "opportunity_id", "status",
                                 "notes", "updated_at"), ("id",)),
]


def copy_table(source, target, table, columns, pk):
    available = {row[1] for row in source.execute(f"PRAGMA table_info({table})")}
    if not available:
        print(f"[PULAR] {table} não existe na origem")
        return 0
    missing = set(columns) - available
    if missing:
        raise RuntimeError(f"{table}: colunas ausentes no SQLite: {sorted(missing)}")
    cols = ", ".join(columns)
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in pk)
    key = ", ".join(pk)
    command = (f"INSERT INTO {table} ({cols}) VALUES %s "
               f"ON CONFLICT ({key}) DO UPDATE SET {updates}")
    rows = source.execute(f"SELECT {cols} FROM {table}")
    count = 0
    with target.cursor() as cursor:
        while (batch := rows.fetchmany(500)):
            if table == "source_postings":
                idx = columns.index("is_active")
                batch = [tuple(bool(value) if j == idx else value
                               for j, value in enumerate(row)) for row in batch]
            execute_values(cursor, command, batch, page_size=500)
            count += len(batch)
    print(f"[OK] {table}: {count:,} registros")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-db", type=Path, required=True,
                        help="Cópia ou SQLite antigo do site, preferencialmente com o servidor parado")
    parser.add_argument("--include-users", action="store_true",
                        help="Importar contas (hashes BCrypt), favoritos e candidaturas")
    args = parser.parse_args()
    dsn = os.environ.get("PG_DSN", "").strip()
    if not dsn:
        parser.error("Defina PG_DSN, por exemplo postgresql://radar:...@localhost:5433/opportunity_radar")
    src = args.from_db.resolve()
    if not src.is_file():
        parser.error(f"SQLite inexistente: {src}")
    # Read-only source; errors in the PostgreSQL transaction do not modify SQLite.
    try:
        with sqlite3.connect(src.as_uri() + "?mode=ro", uri=True) as old:
            if old.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite de origem falhou na verificação de integridade")
            with connect(dsn) as pg:
                for item in TABLES:
                    copy_table(old, pg, *item)
                if args.include_users:
                    for item in PERSONAL_TABLES:
                        copy_table(old, pg, *item)
                # psycopg2 context manager commits on success, rolls back on error.
        print("[SUCESSO] Importação concluída. Dados SQLite originais preservados.")
        return 0
    except Exception as exc:
        print(f"[ERRO] Importação revertida no PostgreSQL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
