"""Create a consistent SQLite copy for the Java MVC demo using SQLite backup.

Safe with WAL and a concurrently running collector. The destination must not
exist; this tool does not modify the collector database.
"""
from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

REQUIRED = frozenset({"opportunities", "source_postings", "opportunity_course_scores"})


def prepare_snapshot(source: Path, destination: Path) -> dict[str, int]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Banco de origem nao encontrado: {source}")
    if destination == source or destination.exists():
        raise FileExistsError(f"Destino ja existe ou e igual a origem: {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Pasta de destino nao existe: {destination.parent}")

    created = False
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)) as original:
            original.execute("PRAGMA query_only = ON")
            tables = {
                row[0] for row in original.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            absent = REQUIRED - tables
            if absent:
                raise ValueError("SQLite nao contem o esquema CP4: " + ", ".join(sorted(absent)))
            with closing(sqlite3.connect(destination, timeout=30)) as copy:
                created = True
                original.backup(copy, pages=512, sleep=0.1)
                quick_check = copy.execute("PRAGMA quick_check").fetchone()[0]
                if quick_check != "ok":
                    raise ValueError(f"Backup SQLite invalido: {quick_check}")
                counts = {
                    name: int(copy.execute("SELECT count(*) FROM " + name).fetchone()[0])
                    for name in ("opportunities", "source_postings")
                }
        return counts
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="SQLite da coleta original")
    parser.add_argument("destination", type=Path, help="Arquivo NOVO para a interface")
    args = parser.parse_args()
    counts = prepare_snapshot(args.source, args.destination)
    print(f"Backup consistente criado: {args.destination.resolve()}")
    print(f"Oportunidades: {counts['opportunities']}; anuncios: {counts['source_postings']}")
