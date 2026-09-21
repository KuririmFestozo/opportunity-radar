"""TOTVS Atração de Talentos: public HTML catalog and JobPosting JSON-LD.

The observed catalog is rendered in a single response and filtered client-side.
There is no documented recency order, so known IDs never truncate discovery.
"""

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from collectors.common import get_text
from collectors.structured_posting import enrich_posting
from models.job import Job
from processing.incremental import report_incremental


BASE = "https://atracaodetalentos.totvs.app"


def _enrich_detail(job, page):
    listing_location = job.location
    enrich_posting(job, page)
    # Keep the same location representation in full and lightweight runs.
    # The listing remains authoritative for changes to the city/state.
    job.location = listing_location or job.location
    soup = BeautifulSoup(page, "html.parser")
    sections = []
    for field in ("description", "responsibilities", "requirements", "desired-requirements", "benefits"):
        node = soup.select_one(f'[data-cy="desktop-{field}"]') or soup.select_one(f'[data-cy="mobile-{field}"]')
        if node and node.get_text(" ", strip=True):
            sections.append(node.get_text(" ", strip=True))
    if sections:
        job.description = "\n\n".join(sections)
    regime = soup.select_one('[data-cy="desktop-regime"], [data-cy="mobile-regime"]')
    if regime:
        job.employment_type = regime.get_text(" ", strip=True) or job.employment_type
    subtitle = soup.select_one('[data-cy="desktop-subtitle"], [data-cy="mobile-subtitle"]')
    if subtitle:
        label = subtitle.get_text(" ", strip=True).split("|")[-1].strip().casefold()
        job.workplace_type = {"presencial": "on-site", "híbrido": "hybrid", "remoto": "remote"}.get(label, job.workplace_type)


def collect_totvs(config: dict) -> list[Job]:
    tenant = config.get("tenant", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", tenant) or not config.get("name"):
        raise ValueError("TOTVS requer name e tenant válidos.")
    page = get_text(f"{BASE}/{tenant}")
    soup = BeautifulSoup(page, "html.parser")
    known = set(config.get("known_source_job_ids") or ())
    jobs = {}
    requests = 1
    details = 0
    jobs_cfg = int(config.get("max_jobs", 500) or 0)
    details_cfg = int(config.get("max_details", 100) or 0)
    max_jobs = jobs_cfg if jobs_cfg > 0 else 100000
    max_details = max(0, min(details_cfg, 100000))
    for row in soup.select("[data-id][data-page-url][data-title]"):
        native_id = row.get("data-id", "").strip()
        title = row.get("data-title", "").strip()
        source_id = f"{config.get('id') or tenant}:{native_id}"
        if not native_id or not title or source_id in jobs:
            continue
        link = row.select_one("a[href]")
        url = urljoin(BASE, link["href"] if link else row["data-page-url"])
        if urlsplit(url).netloc != urlsplit(BASE).netloc or not urlsplit(url).path.startswith(f"/{tenant}/"):
            continue
        # data-remote-string is a translated UI label present on EVERY row.
        # It is not evidence that this particular vacancy is remote.
        location = ""
        if row.get("data-hide-location", "").lower() != "true":
            location = ", ".join(row.get(key, "").strip() for key in ("data-city-name", "data-state-small-name") if row.get(key))
        job = Job(source="totvs", source_job_id=source_id, company=config["name"],
                  title=title, location=location, url=url, source_type="public_html",
                  metadata={"ats": "totvs", "tenant": tenant, "native_id": native_id,
                            "code": row.get("data-code", "")})
        if details < max_details and not (source_id in known and config.get("skip_known_details", False)):
            details += 1
            requests += 1
            try:
                _enrich_detail(job, get_text(url))
            except Exception as exc:
                print(f"[DETAIL] {config['name']} {native_id}: {type(exc).__name__}")
        jobs[source_id] = job
        if len(jobs) >= max_jobs:
            break
    config["_run_seen_ids"] = set(jobs)
    config["_run_coverage"] = "partial" if len(jobs) >= max_jobs else "complete"
    report_incremental(config, jobs.values(), requests)
    if config.get("show_incremental_stats"):
        print(f"[REQUESTS] {config['name']}: {requests - details} listagens | {details} detalhes")
    if config.get("show_incremental_stats") and len(jobs) >= max_jobs:
        print(f"[LIMIT] {config['name']}: max_jobs atingido.")
    return list(jobs.values())
