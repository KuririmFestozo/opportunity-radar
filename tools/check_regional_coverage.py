"""Regional counts from local SQLite/JSON only. No requests, writes or geocoding."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
CITIES = ("São Carlos", "Ibaté", "Araraquara", "Matão", "Gavião Peixoto", "Rio Claro")


def normalize(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value).casefold()) if not unicodedata.combining(c))


def coverage(rows, city=None):
    cities = (city,) if city else CITIES
    counts = {name: Counter() for name in cities}
    seen = set()
    for row in rows:
        identity = (row.get("source"), str(row.get("source_job_id")))
        if identity in seen:
            continue
        seen.add(identity)
        metadata = row.get("metadata") or {}
        location = normalize(" ".join(str(x or "") for x in (
            row.get("location"), metadata.get("resolved_city"), metadata.get("gupy_city"),
        )))
        for name in cities:
            if re.search(r"(?<!\w)" + re.escape(normalize(name)) + r"(?!\w)", location):
                counts[name][row.get("company") or "Empresa desconhecida"] += 1
    return counts


def load_rows(db, json_path=None):
    if json_path:
        payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON deve conter uma lista de vagas.")
        yield from payload
        return
    # mode=ro both protects the existing store and refuses to create a missing DB.
    connection = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        for (raw,) in connection.execute("SELECT job_json FROM jobs WHERE is_active = 1"):
            yield json.loads(raw)
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city")
    parser.add_argument("--db", type=Path, default=ROOT / "data/opportunity_radar.db")
    parser.add_argument("--json", type=Path, help="Usa exportação JSON em vez de SQLite.")
    args = parser.parse_args()
    counts = coverage(load_rows(args.db, args.json), args.city)
    for city, companies in counts.items():
        print(f"{city}: {sum(companies.values())} registros persistidos")
        for company, count in companies.most_common():
            print(f"  {company}: {count}")
    print("Contagens locais por identidade fonte/ID; não equivalem ao total atual na internet.")


if __name__ == "__main__":
    main()
