"""Read public JobPosting JSON-LD shared by the TOTVS and Teamtailor sites."""

import html
import json
import re

from bs4 import BeautifulSoup


def posting_data(page: str) -> dict:
    soup = BeautifulSoup(page, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text().strip().rstrip(";"))
        except (ValueError, TypeError):
            continue
        queue = payload if isinstance(payload, list) else [payload]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "JobPosting":
                return item
            queue.extend(item.get("@graph") or [])
    return {}


def text(value) -> str:
    # TOTVS currently double-escapes Unicode in some JSON-LD string fields.
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), str(value or ""))
    return BeautifulSoup(html.unescape(value), "html.parser").get_text(" ", strip=True)


def enrich_posting(job, page: str):
    data = posting_data(page)
    if not data:
        return job
    job.description = text(data.get("description"))
    job.published_at = data.get("datePosted")
    employment = data.get("employmentType")
    job.employment_type = ", ".join(employment) if isinstance(employment, list) else employment
    if data.get("jobLocationType") == "TELECOMMUTE":
        job.workplace_type = "remote"
    locations = data.get("jobLocation") or []
    if locations:
        job.metadata["job_location"] = locations
    if isinstance(locations, dict):
        locations = [locations]
    labels = []
    for location in locations:
        address = location.get("address", {}) if isinstance(location, dict) else {}
        if isinstance(address, dict):
            country = address.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name")
            label = ", ".join(text(x) for x in [address.get("addressLocality"), address.get("addressRegion"), country] if x)
            if label:
                labels.append(label)
    job.location = " / ".join(labels) or job.location
    if data.get("validThrough"):
        job.metadata["valid_through"] = data["validThrough"]
    return job
