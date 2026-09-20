from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata

from collectors.common import get_json, post_json
from models.job import Job
from processing.incremental import KnownPageStopper, report_incremental


CONFIG_API = "https://izi-api-v2.izirh.io/api/subdomains/{subdomain}"
VACANCIES_API = "https://izi-api.izirh.io/api/sertec-ms-candidates"


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _value_name(value) -> str:
    if isinstance(value, dict):
        return _clean(value.get("name") or value.get("label") or value.get("value"))
    return _clean(value)


def _result(payload):
    if not isinstance(payload, dict):
        return {}
    for key in ("result", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _tenant_id(payload) -> str:
    queue = [payload]
    while queue:
        current = queue.pop(0)
        if not isinstance(current, dict):
            continue
        value = current.get("tenantId") or current.get("tenant_id")
        if value:
            return _clean(value)
        for key in ("result", "data", "configuration", "config"):
            child = current.get(key)
            if isinstance(child, dict):
                queue.append(child)
    return ""


def _workplace_type(value) -> str | None:
    raw = _value_name(value)
    text = unicodedata.normalize("NFKD", raw.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    if not text:
        return None
    if "hibrid" in text or "hybrid" in text or "presencial ou remoto" in text:
        return "hybrid"
    if "remot" in text or "remote" in text or "home office" in text:
        return "remote"
    if "presencial" in text or "on-site" in text or "onsite" in text:
        return "on-site"
    return raw


def _location(item: dict) -> str:
    city = _clean(item.get("city"))
    state = _clean(item.get("state"))
    country = _clean(item.get("country"))
    if city and re.match(r"^[A-Za-z]{2}\s*-\s*.+$", city):
        prefix, rest = city.split("-", 1)
        state = state or prefix.strip().upper()
        city = rest.strip()
    return ", ".join(part for part in (city, state, country) if part)


def _iso_date(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = _clean(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text or None


def _row_to_job(item: dict, *, config: dict, tenant_id: str) -> Job | None:
    native_id = _clean(item.get("id") or item.get("_id") or item.get("vacancyId"))
    title = _clean(item.get("name") or item.get("title"))
    if not native_id or not title:
        return None

    subdomain = _clean(config["subdomain"])
    source_id = _clean(config.get("id") or subdomain)
    contract = _value_name(item.get("typeContraction") or item.get("contractType"))
    description = _clean(
        item.get("description")
        or item.get("jobDescription")
        or item.get("activities")
    )

    return Job(
        source="izirh",
        source_job_id=f"{source_id}:{native_id}",
        company=_clean(config["name"]),
        title=title,
        location=_location(item),
        url=f"https://{subdomain}/visualizar-vaga/{native_id}",
        description=description,
        published_at=_iso_date(
            item.get("createdAt") or item.get("publishedAt") or item.get("published_date")
        ),
        employment_type=contract or None,
        workplace_type=_workplace_type(item.get("workModel") or item.get("work_model")),
        source_type="official_api",
        metadata={
            "ats": "izirh",
            "subdomain": subdomain,
            "tenant_id": tenant_id,
            "pcd": bool(item.get("pcd")),
        },
    )


def collect_izirh(config: dict) -> list[Job]:
    subdomain = _clean(config.get("subdomain"))
    company = _clean(config.get("name"))
    if not subdomain or not company:
        raise ValueError("IziRH requer name e subdomain.")

    tenant_payload = get_json(CONFIG_API.format(subdomain=subdomain))
    tenant_id = _tenant_id(tenant_payload)
    if not tenant_id:
        raise RuntimeError(f"IziRH {subdomain}: configuração pública sem tenantId.")

    page_size = max(10, min(int(config.get("page_size", 100)), 200))
    max_jobs = max(1, min(int(config.get("max_jobs", 500)), 5000))
    stopper = KnownPageStopper(config.get("known_source_job_ids"), config.get("early_stop_known_pages", 2))
    requests = 1  # Public tenant configuration.
    stopped = False
    offset = 0
    seen: set[str] = set()
    jobs: list[Job] = []

    while offset < max_jobs:
        limit = min(page_size, max_jobs - offset)
        response = post_json(
            VACANCIES_API,
            {
                "command": "get_available_vacancies",
                "payload": {
                    "companyId": tenant_id,
                    "offset": offset,
                    "limit": limit,
                    "orderBy": {"name": "createdAt", "order": "desc"},
                    "options": {"filters": True},
                    "subdomain": subdomain,
                },
            },
        )
        requests += 1
        result = _result(response)
        page = result.get("data") or result.get("vacancies") or []
        if not isinstance(page, list):
            raise RuntimeError(f"IziRH {subdomain}: resposta sem lista de vagas.")

        page_ids = set()
        added = 0
        for item in page:
            if not isinstance(item, dict):
                continue
            job = _row_to_job(item, config=config, tenant_id=tenant_id)
            if job:
                page_ids.add(job.source_job_id)
            if not job or job.source_job_id in seen:
                continue
            seen.add(job.source_job_id)
            jobs.append(job)
            added += 1
            if len(jobs) >= max_jobs:
                break

        stopped = stopper.observe(page_ids)
        if stopped:
            break
        offset += len(page)
        try:
            total = int(result.get("vacanciesNumber"))
        except (TypeError, ValueError):
            total = None

        if not page or len(jobs) >= max_jobs:
            break
        if total is not None and offset >= total:
            break
        if total is None and len(page) < limit:
            break
        if added == 0 and len(page) > 0:
            break

    report_incremental(config, jobs, requests, stopped=stopped)
    return jobs
