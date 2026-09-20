"""Teamtailor public HTML /jobs and linked show_more fragments; no private API."""

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from collectors.common import get_text
from collectors.structured_posting import enrich_posting, posting_data, text
from models.job import Job
from processing.incremental import report_incremental


def collect_teamtailor(config: dict) -> list[Job]:
    base = config.get("career_url", "").rstrip("/")
    if urlsplit(base).scheme != "https" or not urlsplit(base).netloc or not config.get("name"):
        raise ValueError("Teamtailor requer name e career_url HTTPS.")
    known = set(config.get("known_source_job_ids") or ())
    max_jobs = max(1, min(int(config.get("max_jobs", 500)), 5000))
    max_details = max(0, min(int(config.get("max_details", 100)), 500))
    jobs = {}
    visited = set()
    signatures = set()
    requests = details = 0
    url = f"{base}/jobs"
    for _ in range(max(1, min(int(config.get("max_pages", 10)), 100))):
        if url in visited:
            break
        visited.add(url)
        page = get_text(url)
        requests += 1
        soup = BeautifulSoup(page, "html.parser")
        refs = {}
        for link in soup.select("a[href]"):
            target = urljoin(base, link["href"])
            match = re.search(r"/jobs/(\d+)-[^/]+/?$", urlsplit(target).path)
            if match and urlsplit(target).netloc == urlsplit(base).netloc:
                title_node = link.select_one("[title]")
                title = title_node.get("title") if title_node else link.get_text(" ", strip=True)
                refs.setdefault(match[1], (target, title))
        signature = frozenset(refs)
        if not signature or signature in signatures:
            break
        signatures.add(signature)
        for native_id, (target, title) in refs.items():
            source_id = f"{config['id']}:{native_id}"
            if source_id in jobs:
                continue
            job = Job(source="teamtailor", source_job_id=source_id, company=config["name"],
                      title=title, location="", url=target, source_type="public_html",
                      metadata={"ats": "teamtailor", "native_id": native_id})
            # Fetch details to keep title/location separate from card decorations.
            if details < max_details and not (source_id in known and config.get("skip_known_details", False)):
                details += 1
                requests += 1
                try:
                    detail = get_text(target)
                    data = posting_data(detail)
                    job.title = text(data.get("title")) or job.title
                    enrich_posting(job, detail)
                except Exception as exc:
                    print(f"[DETAIL] {config['name']} {native_id}: {type(exc).__name__}")
            jobs[source_id] = job
            if len(jobs) >= max_jobs:
                break
        if len(jobs) >= max_jobs:
            break
        next_link = soup.select_one('a[href*="/jobs/show_more?"]')
        if not next_link:
            break
        url = urljoin(base, next_link["href"])
        if urlsplit(url).netloc != urlsplit(base).netloc:
            break
    report_incremental(config, jobs.values(), requests)
    if config.get("show_incremental_stats"):
        print(f"[REQUESTS] {config['name']}: {requests - details} listagens | {details} detalhes")
    return list(jobs.values())
