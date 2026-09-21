from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from collectors.common import post_json
from models.job import Job
from collectors.ats_stats import SearchStats


_LOCALE = re.compile(r"^[a-z]{2}[-_][A-Z]{2}$")


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _board_parts(board_url: str, *, site: str | None = None) -> dict:
    parts = urlsplit(board_url)
    match = re.fullmatch(
        r"(?P<tenant>[A-Za-z0-9_-]+)\.(?P<shard>wd\d+)\.myworkdayjobs\.com",
        parts.netloc,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"URL Workday inválida: {board_url}")

    segments = [segment for segment in parts.path.split("/") if segment]
    locale = ""
    if segments and _LOCALE.fullmatch(segments[0]):
        locale = segments.pop(0)
    site_name = _clean(site) or (segments[0] if segments else "")
    if not site_name:
        raise ValueError(f"Site Workday não identificado em: {board_url}")

    origin = urlunsplit((parts.scheme or "https", parts.netloc, "", "", ""))
    board_path = "/".join(value for value in (locale, site_name) if value)
    return {
        "tenant": match.group("tenant"),
        "site": site_name,
        "locale": locale,
        "origin": origin,
        "board_base": f"{origin}/{board_path}",
        "api": f"{origin}/wday/cxs/{match.group('tenant')}/{site_name}/jobs",
    }


def _native_id(item: dict) -> str:
    for value in item.get("bulletFields") or []:
        text = _clean(value)
        match = re.search(r"\b(?:JR|R)[-_A-Za-z0-9]+\b", text, re.IGNORECASE)
        if match:
            return match.group(0)
    path = _clean(item.get("externalPath"))
    match = re.search(r"/((?:JR|R)[-_A-Za-z0-9]+)(?:/|$)", path, re.IGNORECASE)
    if match:
        return match.group(1)
    return path


def _job_from_item(item: dict, *, config: dict, board: dict) -> Job | None:
    title = _clean(item.get("title"))
    external_path = _clean(item.get("externalPath"))
    native_id = _native_id(item)
    if not title or not external_path or not native_id:
        return None

    source_id = _clean(config.get("id") or board["tenant"])
    return Job(
        source="workday",
        source_job_id=f"{source_id}:{native_id}",
        company=_clean(config["name"]),
        title=title,
        location=_clean(item.get("locationsText")),
        url=f"{board['board_base'].rstrip('/')}{external_path}",
        description="",
        published_at=None,
        employment_type=None,
        workplace_type=None,
        source_type="official_api",
        metadata={
            "ats": "workday",
            "tenant": board["tenant"],
            "site": board["site"],
            "external_path": external_path,
            "posted_on": _clean(item.get("postedOn")),
            "bullet_fields": item.get("bulletFields") or [],
        },
    )


def collect_workday(config: dict) -> list[Job]:
    board = _board_parts(
        _clean(config.get("board_url")),
        site=_clean(config.get("site")) or None,
    )
    queries = [_clean(q) for q in (config.get("queries") or [""]) if _clean(q)]
    if not queries:
        queries = [""]

    configured_max_pages = int(config.get("max_pages_per_query", 0) or 0)
    max_pages = (
        max(1, min(configured_max_pages, 200))
        if configured_max_pages > 0
        else 1000
    )
    configured_max_jobs = int(config.get("max_jobs", 0) or 0)
    max_jobs = (
        max(1, min(configured_max_jobs, 10000))
        if configured_max_jobs > 0
        else 100000
    )
    limit = max(10, min(int(config.get("page_size", 20)), 20))

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": board["board_base"],
    }

    jobs: dict[str, Job] = {}
    requests = 0
    stats = SearchStats(config, queries)
    for query in queries:
        offset = 0
        seen_pages = set()
        for _ in range(max_pages):
            payload = post_json(
                board["api"],
                {
                    "appliedFacets": dict(config.get("applied_facets") or {}),
                    "limit": limit,
                    "offset": offset,
                    "searchText": query,
                },
                headers=headers,
            )
            requests += 1
            postings = payload.get("jobPostings") if isinstance(payload, dict) else None
            stats.page(query, len(postings) if isinstance(postings, list) else 0, payload.get("total") if isinstance(payload, dict) else None)
            if not isinstance(postings, list) or not postings:
                break

            signature = frozenset(str(item.get("externalPath") or "") for item in postings if isinstance(item, dict))
            if signature in seen_pages:
                stats.repeated.add(query)
                break
            seen_pages.add(signature)

            for item in postings:
                if not isinstance(item, dict):
                    continue
                job = _job_from_item(item, config=config, board=board)
                if job and stats.admit(job, query_scoped=bool(query)) and len(jobs) < max_jobs:
                    jobs.setdefault(job.source_job_id, job)
            if len(jobs) >= max_jobs:
                break

            offset += len(postings)
            try:
                total = int(payload.get("total"))
            except (TypeError, ValueError):
                total = None
            if len(postings) < limit or (total is not None and offset >= total):
                break

        else:
            stats.bounded.add(query)

        if len(jobs) >= max_jobs:
            if stats.progress.get(query, (0, None))[1] is None:
                stats.bounded.add(query)
            break

    config["_run_seen_ids"] = set(jobs)
    config["_run_coverage"] = (
        "partial"
        if stats.bounded or stats.repeated or len(jobs) >= max_jobs
        else "complete"
    )
    stats.report(jobs.values(), requests)
    return list(jobs.values())
