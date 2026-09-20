from __future__ import annotations

import re
import unicodedata

from collectors.common import get_json
from models.job import Job
from collectors.ats_stats import SearchStats


API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "job"


def _name(value) -> str:
    if isinstance(value, dict):
        return _clean(value.get("label") or value.get("name") or value.get("value"))
    return _clean(value)


def _location(value) -> str:
    if not isinstance(value, dict):
        return _clean(value)
    parts = [
        _clean(value.get("city")),
        _clean(value.get("region")),
        _clean(value.get("country")),
    ]
    return ", ".join(part for part in parts if part)


def _job_from_item(item: dict, *, config: dict) -> Job | None:
    native_id = _clean(item.get("id") or item.get("uuid"))
    title = _clean(item.get("name") or item.get("title"))
    if not native_id or not title:
        return None

    company_identifier = _clean(config["company_identifier"])
    source_id = _clean(config.get("id") or company_identifier)
    url = (
        item.get("jobAdUrl")
        or item.get("postingUrl")
        or f"https://jobs.smartrecruiters.com/{company_identifier}/{native_id}-{_slugify(title)}"
    )

    workplace = "remote" if item.get("remote") is True else None

    return Job(
        source="smartrecruiters",
        source_job_id=f"{source_id}:{native_id}",
        company=_clean(config["name"]),
        title=title,
        location=_location(item.get("location")),
        url=_clean(url),
        description="",
        published_at=item.get("releasedDate") or item.get("createdOn"),
        employment_type=_name(item.get("typeOfEmployment")) or None,
        workplace_type=workplace,
        source_type="official_api",
        metadata={
            "ats": "smartrecruiters",
            "company_identifier": company_identifier,
            "uuid": _clean(item.get("uuid")),
            "ref_number": _clean(item.get("refNumber")),
            "department": _name(item.get("department")),
        },
    )


def collect_smartrecruiters(config: dict) -> list[Job]:
    company_identifier = _clean(config.get("company_identifier"))
    company = _clean(config.get("name"))
    if not company_identifier or not company:
        raise ValueError("SmartRecruiters requer name e company_identifier.")

    queries = [_clean(q) for q in (config.get("queries") or [""]) if _clean(q)]
    if not queries:
        queries = [""]

    limit = max(10, min(int(config.get("page_size", 100)), 100))
    configured_max_pages = int(config.get("max_pages_per_query", 0) or 0)
    max_pages = (
        max(1, min(configured_max_pages, 200))
        if configured_max_pages > 0
        else 200
    )
    configured_max_jobs = int(config.get("max_jobs", 0) or 0)
    max_jobs = (
        max(1, min(configured_max_jobs, 10000))
        if configured_max_jobs > 0
        else 10000
    )

    jobs: dict[str, Job] = {}
    requests = 0
    stats = SearchStats(config, queries)
    endpoint = API.format(company=company_identifier)

    for query in queries:
        offset = 0
        seen_pages = set()
        for _ in range(max_pages):
            payload = get_json(
                endpoint,
                params={"q": query, "limit": limit, "offset": offset},
            )
            requests += 1
            content = payload.get("content") if isinstance(payload, dict) else None
            stats.page(query, len(content) if isinstance(content, list) else 0, payload.get("totalFound") if isinstance(payload, dict) else None)
            if not isinstance(content, list) or not content:
                break

            signature = frozenset(str(item.get("id") or item.get("uuid") or "") for item in content if isinstance(item, dict))
            if signature in seen_pages:
                stats.repeated.add(query)
                break
            seen_pages.add(signature)

            for item in content:
                if not isinstance(item, dict):
                    continue
                job = _job_from_item(item, config=config)
                if job and stats.admit(job, query_scoped=bool(query)) and len(jobs) < max_jobs:
                    jobs.setdefault(job.source_job_id, job)
            if len(jobs) >= max_jobs:
                break

            offset += len(content)
            try:
                total = int(payload.get("totalFound"))
            except (TypeError, ValueError):
                total = None
            if len(content) < limit or (total is not None and offset >= total):
                break

        else:
            stats.bounded.add(query)

        if len(jobs) >= max_jobs:
            if stats.progress.get(query, (0, None))[1] is None:
                stats.bounded.add(query)
            break

    stats.report(jobs.values(), requests)
    return list(jobs.values())
