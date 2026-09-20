"""Read-only Gupy Global diagnostics: python check_regional_sources.py [--live]."""

import argparse
import json
from pathlib import Path

from collectors.gupy_global import _collect_segment


TARGETS = {"Faber-Castell": ("faber", "São Carlos"), "TATU Marchesan": ("marchesan", "Matão")}


def regional_matches(jobs):
    return {
        name: [job for job in jobs
               if job.get("source") == "gupy_global"
               and token in str(job.get("company", "")).casefold()]
        for name, (token, _) in TARGETS.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Consulta limitada ao endpoint público global, sem persistência.")
    args = parser.parse_args()
    if args.live:
        jobs = [job.to_dict() for _, city in TARGETS.values()
                for job in _collect_segment(page_size=100, max_pages=2, city=city)]
    else:
        path = Path("output/jobs.json")
        jobs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    for company, matches in regional_matches(jobs).items():
        print(f"{company}: {len(matches)} registros Gupy Global")
        for job in matches[:3]:
            print(f"  {job['source_job_id']} | {job['title']} | {job['url']}")
    print("Ausência neste recorte não prova ausência na fonte. O diagnóstico ao vivo não garante inclusão no lote early-career agendado.")


if __name__ == "__main__":
    main()
