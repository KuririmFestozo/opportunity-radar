"""Create a clearly fictional, self-contained SQLite demo for MVC review.

Never run this against your collector database; refuses to overwrite any file.
Usage:
    python web-mvc/tools/create_demo_db.py web-mvc/demo.db
"""
from __future__ import annotations

import argparse
import sqlite3
import uuid
from pathlib import Path

DEMO = [
    ("Aurora Energia (exemplo)", "Estágio em Engenharia Elétrica",
     "São Carlos, SP", "Estágio", "hybrid", 92),
    ("Horizonte Tech (exemplo)", "Desenvolvedor Júnior",
     "Campinas, SP", "Júnior", "remote", 77),
    ("Verde Futuro (exemplo)", "Pesquisa em Sustentabilidade",
     "São Paulo, SP", "Pesquisa", "on-site", 85),
    ("Atlas Sistemas (exemplo)", "Estágio em Software",
     "Ribeirão Preto, SP", "Estágio", "hybrid", 91),
    ("Oficina Solar (exemplo)", "Programa de Trainee",
     "Sorocaba, SP", "Trainee", "on-site", 68),
    ("Laboratório Terra (exemplo)", "Estágio em Análise de Dados",
     "Araraquara, SP", "Estágio", "remote", 82),
]

def create_demo(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Arquivo ja existe (nao sera alterado): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE opportunities (
          id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
          description TEXT NOT NULL, location_text TEXT NOT NULL,
          workplace_type TEXT, employment_type TEXT, published_at TEXT,
          canonical_url TEXT, updated_at TEXT NOT NULL
        );
        CREATE TABLE source_postings (
          source TEXT NOT NULL, source_job_id TEXT NOT NULL,
          opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
          is_active INTEGER NOT NULL, url TEXT, last_seen_at TEXT,
          PRIMARY KEY(source, source_job_id)
        );
        CREATE INDEX idx_demo_posting_opportunity ON source_postings(opportunity_id);
        CREATE TABLE opportunity_course_scores (
          opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
          course_id TEXT NOT NULL, score INTEGER NOT NULL,
          PRIMARY KEY(opportunity_id, course_id)
        );
        """)
        for index, (company, title, location, kind, workplace, score) in enumerate(DEMO, 1):
            oid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"radar-mvc-demo:{index}"))
            url = f"https://example.org/oportunidade/{index}"
            conn.execute(
                """INSERT INTO opportunities (
                  id, company, title, description, location_text, workplace_type,
                  employment_type, published_at, canonical_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (oid, company, title, "Dado ilustrativo para demonstração acadêmica.",
                 location, workplace, kind, "2026-11-01T12:00:00Z", url, "2026-11-05T12:00:00Z"),
            )
            conn.execute(
                "INSERT INTO source_postings VALUES (?, ?, ?, ?, ?, ?)",
                ("demo", str(index), oid, 1, url, "2026-11-05T12:00:00Z"),
            )
            conn.execute(
                "INSERT INTO opportunity_course_scores VALUES (?, ?, ?)",
                (oid, "engenharia_eletrica", score),
            )
        conn.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path)
    args = parser.parse_args()
    create_demo(args.db)
    print(f"Banco demo criado: {args.db.resolve()}")
