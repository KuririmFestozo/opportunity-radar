"""Bettha public internship and trainee catalog."""
from __future__ import annotations

import re

from collectors.common import get_text
from collectors.public_early_career import (
    canonical_url,
    clean,
    employment_from_text,
    nearest_card,
    soup,
    stable_native_id,
)
from models.job import Job

DEFAULT_URL = "https://www.bettha.com/vagas"


def _company(card) -> str:
    if card is not None:
        image = card.find("img", alt=True)
        if image:
            alt = clean(image.get("alt"))
            alt = re.sub(r"(?i)^logo\s+(?:da|do|de)\s+", "", alt).strip()
            if alt:
                return alt
    return "Bettha / empresa anunciante"


def _parse(html: str, base_url: str) -> list[Job]:
    doc = soup(html)
    jobs: dict[str, Job] = {}

    for link in doc.find_all("a", href=True):
        label = clean(link.get_text(" ", strip=True))
        if "candidatar" not in label.casefold():
            continue

        card = nearest_card(link)
        if card is None:
            continue

        heading = card.find(["h2", "h3", "h4"])
        title = clean(heading.get_text(" ", strip=True)) if heading else ""
        text = clean(card.get_text(" ", strip=True))
        employment = employment_from_text(text) or employment_from_text(title)
        if not title or employment is None:
            continue

        url = canonical_url(base_url, link.get("href"))
        company = _company(card)
        native = stable_native_id(url, f"{company}|{title}")

        jobs.setdefault(
            f"bettha:{native}",
            Job(
                source="bettha",
                source_job_id=f"bettha:{native}",
                company=company,
                title=title,
                location="Brasil",
                url=url,
                description=text,
                employment_type=employment,
                source_type="public_html",
                metadata={
                    "platform": "bettha",
                    "coverage": "public_open_programs",
                },
            ),
        )

    return list(jobs.values())


def collect_bettha(config: dict) -> list[Job]:
    url = config.get("list_url") or DEFAULT_URL
    jobs = _parse(get_text(url), url)
    configured = int(config.get("max_jobs", 0) or 0)
    if configured > 0:
        jobs = jobs[:configured]
    if config.get("show_incremental_stats", True):
        print(f"[PUBLIC] Bettha: {len(jobs)} vagas/programas públicos")
    return jobs
