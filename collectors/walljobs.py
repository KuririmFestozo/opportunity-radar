"""WallJobs public vacancies; no login or candidate data."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from collectors.common import get_text
from collectors.public_early_career import canonical_url, clean, employment_from_text, first_heading, location_from_text, nearest_card, salary_from_text, soup, stable_native_id
from models.job import Job

DEFAULT_LIST_URL = "https://app.walljobs.com.br/vagas"
FALLBACK_URL = "https://app.walljobs.com.br/"


def _parse_page(html: str, base_url: str) -> list[Job]:
    doc = soup(html)
    jobs = {}
    for link in doc.select('a[href*="/vagas/"]'):
        url = canonical_url(base_url, link.get("href"))
        parts = urlsplit(url)
        if parts.netloc != "app.walljobs.com.br" or "/vagas/" not in parts.path:
            continue
        card = nearest_card(link)
        text = clean(card.get_text(" ", strip=True) if card else "")
        title = first_heading(card)
        if not title or title.casefold() in {"vagas", "buscar vagas"}:
            continue
        native_id = stable_native_id(url, title)
        expiration = None
        match = re.search(r"Expira\s+em\s+(\d{2}/\d{2}/\d{4})", text, re.I)
        if match:
            expiration = match.group(1)
        job = Job(
            source="walljobs",
            source_job_id=f"walljobs:{native_id}",
            company="WallJobs / empresa anunciante",
            title=title,
            location=location_from_text(text.replace(title, " ", 1)),
            url=url,
            employment_type=employment_from_text(text),
            source_type="public_html",
            salary=salary_from_text(text),
            metadata={"platform": "walljobs", "expiration_date": expiration, "coverage": "public_listing"},
        )
        jobs.setdefault(job.source_job_id, job)
    return list(jobs.values())


def collect_walljobs(config: dict) -> list[Job]:
    urls = [config.get("list_url") or DEFAULT_LIST_URL]
    fallback = config.get("fallback_url", FALLBACK_URL)
    if fallback and fallback not in urls:
        urls.append(fallback)
    out = {}
    requests = 0
    for url in urls:
        html = get_text(url)
        requests += 1
        for job in _parse_page(html, url):
            out.setdefault(job.source_job_id, job)
        if out:
            break
    configured = int(config.get("max_jobs", 0) or 0)
    jobs = list(out.values())
    if configured > 0:
        jobs = jobs[:configured]
    if config.get("show_incremental_stats", True):
        known = set(config.get("known_source_job_ids") or ())
        ids = {j.source_job_id for j in jobs}
        print(f"[INCREMENTAL] WallJobs: {len(ids & known)} conhecidos | {len(ids - known)} novos | {requests} requests")
        if not jobs:
            print("[SKIP] WallJobs: catálogo público não expôs cards parseáveis nesta execução.")
    return jobs
