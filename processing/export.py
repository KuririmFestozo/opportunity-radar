import csv
import json
from pathlib import Path
from config.catalogs import COURSES, INTENTS
from models.job import Job
from models.match import JobMatch
from models.profile import SearchProfile

OUTPUT_DIR = Path("output")


def export_all(jobs, profiles, matches, search_links, stats):
    OUTPUT_DIR.mkdir(exist_ok=True)
    job_dicts = [j.to_dict() for j in jobs]
    profile_dicts = [p.to_dict() for p in profiles]
    match_dicts = [m.to_dict() for m in matches]
    data = {
        "jobs": job_dicts,
        "profiles": profile_dicts,
        "matches": match_dicts,
        "courses": COURSES,
        "intents": INTENTS,
        "search_links": search_links,
        "stats": stats,
    }
    _dump("jobs.json", job_dicts)
    _dump("profiles.json", profile_dicts)
    _dump("matches.json", match_dicts)
    _dump("search_links.json", search_links)
    _dump("stats.json", stats)
    _dump("dashboard_data.json", data)
    _export_csv(jobs)
    _export_html(data)


def _dump(name, data):
    with (OUTPUT_DIR / name).open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _export_csv(jobs: list[Job]):
    fields = [
        "source", "source_job_id", "company", "title", "location",
        "latitude", "longitude", "employment_type", "workplace_type",
        "detected_intents", "course_scores", "url",
    ]
    with (OUTPUT_DIR / "jobs.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for j in jobs:
            writer.writerow({
                "source": j.source,
                "source_job_id": j.source_job_id,
                "company": j.company,
                "title": j.title,
                "location": j.location,
                "latitude": j.latitude,
                "longitude": j.longitude,
                "employment_type": j.employment_type,
                "workplace_type": j.workplace_type,
                "detected_intents": "; ".join(j.detected_intents),
                "course_scores": json.dumps(j.course_scores, ensure_ascii=False),
                "url": j.url,
            })


def _export_html(data):
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    template_path = Path(__file__).resolve().parent.parent / "web" / "dashboard.html"
    template = template_path.read_text(encoding="utf-8")
    page = template.replace("__DASHBOARD_DATA__", payload)
    (OUTPUT_DIR / "index.html").write_text(page, encoding="utf-8")
