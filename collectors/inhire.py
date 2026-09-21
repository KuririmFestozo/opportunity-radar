from __future__ import annotations

import re
import unicodedata

from collectors.common import get_json
from models.job import Job
from processing.incremental import report_incremental


API_URL = "https://api.inhire.app/job-posts/public/pages"
_CLOSED = {"closed", "inactive", "archived", "cancelled", "canceled", "encerrada", "encerrado"}


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text or "vaga"


def _value_name(value) -> str:
    if isinstance(value, dict):
        return _clean(value.get("name") or value.get("label") or value.get("value"))
    return _clean(value)


def _workplace_type(value) -> str | None:
    text = unicodedata.normalize("NFKD", _value_name(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    if not text:
        return None
    if "hybrid" in text or "hibrid" in text:
        return "hybrid"
    if "remote" in text or "remot" in text or "home office" in text:
        return "remote"
    if "on-site" in text or "onsite" in text or "presencial" in text:
        return "on-site"
    return _value_name(value) or None


def _location(value) -> str:
    if isinstance(value, dict):
        parts = [
            _clean(value.get("city") or value.get("name")),
            _clean(value.get("state") or value.get("region")),
            _clean(value.get("country")),
        ]
        return ", ".join(part for part in parts if part)
    if isinstance(value, list):
        return " / ".join(_clean(item) for item in value if _clean(item))
    return _clean(value)


def _jobs_payload(data):
    if isinstance(data, dict):
        for key in ("jobsPage", "jobs", "jobPosts"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        nested = data.get("data") or data.get("result")
        if isinstance(nested, dict):
            return _jobs_payload(nested)
    return []


def collect_inhire(config: dict) -> list[Job]:
    tenant = _clean(config.get("tenant"))
    company = _clean(config.get("name"))
    source_id = _clean(config.get("id") or tenant)
    if not tenant or not company:
        raise ValueError("InHire requer name e tenant.")

    payload = get_json(API_URL, headers={"X-Tenant": tenant})
    items = _jobs_payload(payload)
    jobs_cfg = int(config.get("max_jobs", 500) or 0)
    max_jobs = jobs_cfg if jobs_cfg > 0 else 100000

    jobs: list[Job] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        job_id = _clean(item.get("jobId") or item.get("id") or item.get("_id"))
        title = _clean(item.get("displayName") or item.get("title") or item.get("name"))
        if not job_id or not title or job_id in seen:
            continue

        status = _clean(item.get("status")).casefold()
        if status in _CLOSED:
            continue

        seen.add(job_id)
        jobs.append(
            Job(
                source="inhire",
                source_job_id=f"{source_id}:{job_id}",
                company=company,
                title=title,
                location=_location(item.get("location")),
                url=f"https://{tenant}.inhire.app/vagas/{job_id}/{_slugify(title)}",
                description=_clean(item.get("description")),
                published_at=item.get("publishedAt") or item.get("createdAt"),
                employment_type=_value_name(
                    item.get("employmentType")
                    or item.get("contractType")
                    or item.get("typeContraction")
                ) or None,
                workplace_type=_workplace_type(
                    item.get("workplaceType") or item.get("workModel")
                ),
                source_type="official_api",
                metadata={
                    "ats": "inhire",
                    "tenant": tenant,
                    "status": _clean(item.get("status")),
                },
            )
        )
        if len(jobs) >= max_jobs:
            break
    config["_run_seen_ids"] = {job.source_job_id for job in jobs}
    config["_run_coverage"] = (
        "partial"
        if len(items) > max_jobs and len(jobs) >= max_jobs
        else "complete"
    )
    report_incremental(config, jobs, 1)
    if (config.get("show_incremental_stats") and jobs
            and {job.source_job_id for job in jobs} <= set(config.get("known_source_job_ids") or ())):
        print(f"[FAST-STOP] {company}: catálogo conhecido; conteúdo ainda verificado pelo JobStore.")
    return jobs
