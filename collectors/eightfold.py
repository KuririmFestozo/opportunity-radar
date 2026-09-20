"""Eightfold PCS public career-site API (not an authenticated integration API)."""

from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from collectors.common import get_json
from collectors.structured_posting import text
from models.job import Job
from processing.incremental import report_incremental


def collect_eightfold(config: dict) -> list[Job]:
    base = config.get("career_url", "").rstrip("/")
    domain = config.get("domain")
    if urlsplit(base).scheme != "https" or not domain or not config.get("id"):
        raise ValueError("Eightfold requer career_url HTTPS, domain e id.")
    known = set(config.get("known_source_job_ids") or ())
    max_jobs = max(1, min(int(config.get("max_jobs", 500)), 3000))
    max_pages = max(1, min(int(config.get("max_pages", 30)), 100))
    max_details = max(0, min(int(config.get("max_details", 100)), 500))
    jobs, signatures = {}, set()
    requests = details = offset = 0
    total = None
    exhausted = False
    for _ in range(max_pages):
        payload = get_json(base + "/api/pcsx/search", params={
            "domain": domain, "query": "", "location": "", "start": offset,
        })
        requests += 1
        data = payload.get("data") or {}
        rows = data.get("positions")
        if not isinstance(rows, list):
            raise RuntimeError("Eightfold: resposta sem data.positions.")
        try:
            total = int(data.get("count"))
        except (ValueError, TypeError):
            total = None
        if not rows:
            exhausted = True
            break
        signature = frozenset(str(row.get("id")) for row in rows if isinstance(row, dict))
        if signature in signatures:
            break
        signatures.add(signature)
        offset += len(rows)
        for row in rows:
            if not isinstance(row, dict) or not row.get("id") or not row.get("name"):
                continue
            source_id = f"{config['id']}:{row['id']}"
            if source_id in jobs:
                continue
            url = urljoin(base, row.get("positionUrl") or f"/careers/job/{row['id']}")
            if urlsplit(url).netloc != urlsplit(base).netloc:
                continue
            published = None
            if isinstance(row.get("postedTs"), (int, float)):
                try:
                    published = datetime.fromtimestamp(row["postedTs"], timezone.utc).isoformat()
                except (ValueError, OSError, OverflowError):
                    pass
            locations = row.get("locations") or []
            job = Job(source="eightfold", source_job_id=source_id, company=config["name"],
                      title=text(row["name"]), location=" / ".join(locations) if isinstance(locations, list) else text(locations),
                      url=url, published_at=published, source_type="public_api",
                      workplace_type={"onsite": "on-site", "hybrid": "hybrid", "remote": "remote"}.get(row.get("workLocationOption")),
                      metadata={"ats": "eightfold", "domain": domain, "ats_job_id": row.get("atsJobId")})
            if details < max_details and not (source_id in known and config.get("skip_known_details")):
                details += 1
                requests += 1
                try:
                    detail = get_json(base + "/api/pcsx/position_details", params={
                        "domain": domain, "position_id": row["id"], "hl": "en",
                    }).get("data") or {}
                    job.description = text(detail.get("jobDescription"))
                except Exception as exc:
                    print(f"[DETAIL] {config['name']} {row['id']}: {type(exc).__name__}")
            jobs[source_id] = job
            if len(jobs) >= max_jobs:
                break
        if total is not None and offset >= total and (len(jobs) < max_jobs or len(jobs) >= total):
            exhausted = True
            break
        if len(jobs) >= max_jobs:
            break
    report_incremental(config, jobs.values(), requests)
    if not exhausted:
        remaining = max(0, total - len(jobs)) if total is not None else "indeterminado"
        print(f"[LIMIT] {config['name']}: catálogo incompleto; {remaining} registros potencialmente não retornados.")
    if config.get("show_incremental_stats"):
        print(f"[REQUESTS] {config['name']}: {requests - details} listagens | {details} detalhes")
    return list(jobs.values())
