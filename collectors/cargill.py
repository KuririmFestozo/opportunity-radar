"""Cargill official public careers catalog."""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from collectors.common import get_text
from collectors.public_early_career import clean, soup, stable_native_id
from models.job import Job

BASE = "https://careers.cargill.com"
START_URL = "https://careers.cargill.com/en/search-jobs?acm=ALL&alrpm=ALL&ascf=%5B%7B%22key%22:%22job_type%22,%22value%22:%22Campus%22%7D,%7B%22key%22:%22job_type%22,%22value%22:%22University%22%7D%5D"


def _same_host(url: str) -> bool:
    return urlsplit(url).netloc == "careers.cargill.com"


def _parse_page(html: str, page_url: str) -> tuple[list[Job], str | None]:
    doc = soup(html)
    jobs: dict[str, Job] = {}

    for link in doc.find_all("a", href=True):
        href = clean(link.get("href"))
        if "/job/" not in href:
            continue

        url = urljoin(page_url, href)
        if not _same_host(url):
            continue

        label = clean(link.get_text(" ", strip=True))
        if not label:
            continue

        parent = link.parent
        text = clean(parent.get_text(" ", strip=True) if parent else label)
        location = text.replace(label, "", 1).strip(" -|,")

        native = stable_native_id(url, label)
        jobs.setdefault(
            f"cargill:{native}",
            Job(
                source="cargill",
                source_job_id=f"cargill:{native}",
                company="Cargill",
                title=label,
                location=location,
                url=url,
                description=text,
                source_type="official_public_careers",
                metadata={
                    "platform": "cargill_careers",
                    "coverage": "public_catalog",
                },
            ),
        )

    next_url = None
    for link in doc.find_all("a", href=True):
        label = clean(link.get_text(" ", strip=True)).casefold()
        rel = {str(x).casefold() for x in (link.get("rel") or [])}
        if label == "next" or "next" in rel:
            candidate = urljoin(page_url, clean(link.get("href")))
            if _same_host(candidate):
                next_url = candidate
                break

    return list(jobs.values()), next_url


def collect_cargill(config: dict) -> list[Job]:
    start_url = config.get("list_url") or START_URL
    pages_cfg = int(config.get("max_pages", 10) or 0)
    max_pages = pages_cfg if pages_cfg > 0 else 500
    jobs_cfg = int(config.get("max_jobs", 0) or 0)

    found: dict[str, Job] = {}
    visited: set[str] = set()
    url = start_url

    for _ in range(max_pages):
        if not url or url in visited:
            break
        visited.add(url)

        page_jobs, next_url = _parse_page(get_text(url), url)
        for job in page_jobs:
            found.setdefault(job.source_job_id, job)
            if jobs_cfg > 0 and len(found) >= jobs_cfg:
                return list(found.values())[:jobs_cfg]

        url = next_url

    return list(found.values())
