"""Global collector for the public Gupy candidate portal.

This is intentionally separate from ``gupy_api.py``. The latter is Gupy's
authenticated official API and is scoped to the token/account. This collector
uses the JSON endpoint consumed by the public candidate portal.

Because the public portal endpoint is not documented as a stable integration
contract, all parsing is defensive and the old per-company collector remains
available as a fallback in configuration.
"""

from __future__ import annotations

import time
from typing import Iterable

import requests

from collectors.common import PUBLIC_DELAY, get_json
from models.job import Job


API_URL = "https://employability-portal.gupy.io/api/v1/jobs"
PORTAL_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://portal.gupy.io",
    "Referer": "https://portal.gupy.io/",
}

DEFAULT_NATIVE_JOB_TYPES = [
    "vacancy_type_internship",
    "vacancy_type_summer",
    "vacancy_type_trainee",
    "vacancy_type_apprentice",
]

DEFAULT_KEYWORD_QUERIES = [
    "junior",
    "júnior",
    "entry level",
    "new grad",
    "graduate engineer",
    "co-op",
    "research",
    "iniciação científica",
    "summer job",
    "trabalho de férias",
]


def collect_gupy_global(config: dict | None = None) -> list[Job]:
    """Collect a broad early-career slice from Gupy's public global portal.

    Strategy:
    1. Pull the native early-career vacancy types without course/location
       restrictions (internship, summer, trainee, apprentice).
    2. Add keyword passes for opportunity classes that do not have a dedicated
       Gupy vacancy type (co-op, research, entry-level and seasonal jobs).
    3. Deduplicate by Gupy id/URL before returning.

    Collection is intentionally independent from user profiles. Course,
    distance, country and other preference filters happen later in the radar.
    """
    cfg = config or {}
    page_size = max(10, min(int(cfg.get("page_size", 100)), 100))
    native_pages = max(1, int(cfg.get("max_pages_per_native_type", 8)))
    keyword_pages = max(1, int(cfg.get("max_pages_per_keyword", 2)))
    native_types = list(cfg.get("native_job_types") or DEFAULT_NATIVE_JOB_TYPES)
    keyword_queries = list(cfg.get("keyword_queries") or DEFAULT_KEYWORD_QUERIES)

    jobs: list[Job] = []

    for job_type in native_types:
        jobs.extend(
            _collect_segment(
                page_size=page_size,
                max_pages=native_pages,
                job_type=job_type,
            )
        )

    for keyword in keyword_queries:
        jobs.extend(
            _collect_segment(
                page_size=page_size,
                max_pages=keyword_pages,
                keyword=keyword,
            )
        )

    return _deduplicate_gupy(jobs)



def collect_gupy_nearby(city_names: Iterable[str], config: dict | None = None) -> list[Job]:
    """Target the Gupy portal by exact city names for an on-demand radius search."""
    cfg = config or {}
    page_size = max(10, min(int(cfg.get("page_size", 100)), 100))
    max_pages = max(1, min(int(cfg.get("nearby_max_pages_per_city", 2)), 5))
    native_types = list(cfg.get("native_job_types") or DEFAULT_NATIVE_JOB_TYPES)
    combined_types = ",".join(native_types)
    keyword_city_limit = max(0, int(cfg.get("nearby_keyword_city_limit", 4)))
    keyword_queries = list(cfg.get("nearby_keyword_queries") or ["junior", "co-op", "research"])

    cities = []
    seen = set()
    for city in city_names:
        cleaned = _clean(city)
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            cities.append(cleaned)

    jobs: list[Job] = []
    for city in cities:
        jobs.extend(
            _collect_segment(
                page_size=page_size,
                max_pages=max_pages,
                job_type=combined_types,
                city=city,
            )
        )

    for city in cities[:keyword_city_limit]:
        for keyword in keyword_queries:
            jobs.extend(
                _collect_segment(
                    page_size=page_size,
                    max_pages=1,
                    keyword=keyword,
                    city=city,
                )
            )

    return _deduplicate_gupy(jobs)

def _collect_segment(
    *,
    page_size: int,
    max_pages: int,
    keyword: str | None = None,
    job_type: str | None = None,
    city: str | None = None,
    state: str | None = None,
    country: str | None = None,
) -> list[Job]:
    jobs: list[Job] = []

    for page_index in range(max_pages):
        params = _build_params(
            offset=page_index * page_size,
            limit=page_size,
            keyword=keyword,
            job_type=job_type,
            city=city,
            state=state,
            country=country,
        )
        payload = _get_payload_with_type_fallback(params, job_type)
        items = payload.get("data", []) if isinstance(payload, dict) else []

        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            job = job_from_item(item)
            if job is not None:
                jobs.append(job)

        # pagination.total has behaved inconsistently across versions of the
        # public portal. A short page is the safest end-of-list signal.
        if len(items) < page_size:
            break

        time.sleep(PUBLIC_DELAY)

    return jobs


def _build_params(
    *,
    offset: int,
    limit: int,
    keyword: str | None = None,
    job_type: str | None = None,
    city: str | None = None,
    state: str | None = None,
    country: str | None = None,
) -> dict:
    params: dict[str, str | int] = {
        "offset": offset,
        "limit": min(limit, 100),
        "sortBy": "publishedDate",
    }
    if keyword:
        params["jobName"] = keyword
    if job_type:
        # This is the parameter name observed in the portal's own requests.
        params["type"] = job_type
    if city:
        params["city"] = city
    if state:
        params["state"] = state
    if country:
        params["country"] = country
    return params



def _get_payload_with_type_fallback(params: dict, job_type: str | None) -> dict:
    """Support both filter names seen across public portal generations.

    The portal has used ``type`` in its own network requests, while newer
    community clients also report ``jobTypes``. We prefer ``type`` and only
    retry with the alias when the first request is rejected.
    """
    try:
        return get_json(API_URL, params=params, headers=PORTAL_HEADERS)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if not job_type or status not in {400, 404, 422}:
            raise

        fallback = dict(params)
        fallback.pop("type", None)
        fallback["jobTypes"] = job_type
        return get_json(API_URL, params=fallback, headers=PORTAL_HEADERS)

def job_from_item(item: dict) -> Job | None:
    title = _clean(item.get("name"))
    url = _clean(item.get("jobUrl") or item.get("publicUrl") or item.get("url"))
    job_id = _clean(item.get("id")) or url

    if not title or not url or not job_id:
        return None

    city = _clean(item.get("city"))
    state = _clean(item.get("state"))
    country = _clean(item.get("country"))
    workplace = _normalize_workplace(item)
    location = _location(city, state, country, workplace)
    gupy_type = _job_type(item)

    metadata = {
        "gupy_job_type": gupy_type,
        "gupy_city": city,
        "gupy_state": state,
        "gupy_country": country,
        "career_page_name": _clean(item.get("careerPageName")),
    }
    resolved_country = _country_code(country)
    if resolved_country:
        metadata["resolved_country"] = resolved_country

    return Job(
        source="gupy_global",
        source_type="public_api",
        source_job_id=job_id,
        company=_clean(item.get("careerPageName")) or "Gupy",
        title=title,
        location=location,
        url=url,
        description=_description(item),
        published_at=(
            item.get("publishedDate")
            or item.get("publishedAt")
            or item.get("createdAt")
        ),
        employment_type=gupy_type or None,
        workplace_type=workplace or None,
        metadata=metadata,
    )


def _description(item: dict) -> str:
    parts: list[str] = []
    for key in (
        "description",
        "responsibilities",
        "prerequisites",
        "requirements",
        "additionalInformation",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts)[:16000]


def _job_type(item: dict) -> str:
    return _clean(
        item.get("jobType")
        or item.get("type")
        or item.get("vacancyType")
    )


def _normalize_workplace(item: dict) -> str:
    raw = _clean(item.get("workplaceType")).lower()
    aliases = {
        "onsite": "on-site",
        "on_site": "on-site",
        "presencial": "on-site",
        "hibrido": "hybrid",
        "híbrido": "hybrid",
        "remoto": "remote",
    }
    raw = aliases.get(raw, raw)
    if raw in {"remote", "hybrid", "on-site"}:
        return raw
    if item.get("isRemoteWork") is True:
        return "remote"
    return ""


def _location(city: str, state: str, country: str, workplace: str) -> str:
    parts = [part for part in (city, state) if part]
    if parts:
        location = ", ".join(parts)
        if country and country.lower() not in location.lower():
            location = f"{location}, {country}"
        return location
    if country:
        return f"{country} - Remote" if workplace == "remote" else country
    return "Remote" if workplace == "remote" else ""


def _country_code(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"br", "brazil", "brasil"}:
        return "BR"
    if normalized in {
        "us",
        "usa",
        "united states",
        "united states of america",
    }:
        return "US"
    return None


def _deduplicate_gupy(jobs: Iterable[Job]) -> list[Job]:
    unique: dict[str, Job] = {}
    for job in jobs:
        key = job.source_job_id or job.url
        current = unique.get(key)
        if current is None:
            unique[key] = job
            continue

        # Keep the richest duplicate when the same vacancy appears in more
        # than one keyword/native-type segment.
        current_quality = len(current.description or "") + len(current.location or "")
        candidate_quality = len(job.description or "") + len(job.location or "")
        if candidate_quality > current_quality:
            unique[key] = job
    return list(unique.values())


def _clean(value) -> str:
    return " ".join(str(value or "").split()).strip()
