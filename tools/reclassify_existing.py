from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.search_links import build_search_links
from main import active_profiles
from models.job import Job
from processing.classification import classify_job
from processing.export import export_all
from processing.matching import match_job


OUTPUT = ROOT / "output"
JOBS_PATH = OUTPUT / "jobs.json"
STATS_PATH = OUTPUT / "stats.json"


def _load_jobs() -> list[Job]:
    if not JOBS_PATH.exists():
        raise SystemExit("[ERRO] output/jobs.json não existe. Rode python main.py ao menos uma vez.")
    raw = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    allowed = {field.name for field in fields(Job)}
    jobs = []
    for item in raw:
        if isinstance(item, dict):
            jobs.append(Job(**{key: value for key, value in item.items() if key in allowed}))
    return jobs


def _load_stats() -> dict:
    if not STATS_PATH.exists():
        return {}
    try:
        return json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> None:
    jobs = _load_jobs()
    intent_counts = Counter()
    geocoded = 0

    for job in jobs:
        classify_job(job)
        if job.latitude is not None and job.longitude is not None:
            geocoded += 1
        for intent_id in job.detected_intents:
            intent_counts[intent_id] += 1

    profiles = active_profiles()
    matches = [match_job(job, profile) for profile in profiles for job in jobs]
    links = build_search_links(profiles)

    stats = _load_stats()
    stats.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unique_jobs": len(jobs),
        "geocoded_jobs": geocoded,
        "profiles": [profile.id for profile in profiles],
        "intent_counts": dict(intent_counts),
    })
    stats.setdefault("raw_jobs", len(jobs))
    stats.setdefault("sources", dict(Counter(job.source for job in jobs)))

    export_all(jobs, profiles, matches, links, stats)

    print(f"[OK] {len(jobs)} vagas reclassificadas sem nova coleta.")
    print("[OK] output/jobs.json, dashboard_data.json e index.html atualizados.")


if __name__ == "__main__":
    main()
