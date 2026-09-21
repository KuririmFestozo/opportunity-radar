"""TAQE public national early-career catalog."""
from __future__ import annotations

from urllib.parse import urlsplit

from collectors.common import get_text
from collectors.public_early_career import (
    canonical_url,
    clean,
    employment_from_text,
    location_from_text,
    nearest_card,
    salary_from_text,
    soup,
    stable_native_id,
    workplace_from_text,
)
from models.job import Job

DEFAULT_URL = "https://vagas.taqe.com.br/"


def _location(card) -> str:
    if card is None:
        return ""
    strings = [clean(x) for x in card.stripped_strings if clean(x)]
    for value in strings:
        low = value.casefold()
        if (
            value.startswith("R$")
            or "benefício" in low
            or "beneficio" in low
            or "saiba mais" in low
            or "estágio" in low
            or "estagio" in low
        ):
            continue
        if 2 <= len(value) <= 100 and not any(ch.isdigit() for ch in value):
            return value
    return ""


def _parse(html: str, base_url: str) -> list[Job]:
    doc = soup(html)
    jobs: dict[str, Job] = {}

    for link in doc.find_all("a", href=True):
        label = clean(link.get_text(" ", strip=True))
        if "saiba mais" not in label.casefold():
            continue

        url = canonical_url(base_url, link.get("href"))
        if urlsplit(url).netloc != "vagas.taqe.com.br":
            continue

        card = nearest_card(link)
        if card is None:
            continue

        headings = [
            clean(node.get_text(" ", strip=True))
            for node in card.find_all(["h2", "h3", "h4", "h5"])
            if clean(node.get_text(" ", strip=True))
        ]
        if not headings:
            continue

        company = headings[0] if len(headings) > 1 else "TAQE / empresa anunciante"
        generic = {
            "estágio", "estagio", "trainee", "jovem aprendiz", "aprendiz",
            "júnior", "junior",
        }
        candidates = [
            value for value in headings[1:]
            if value.casefold().strip() not in generic
        ]
        title = candidates[0] if candidates else headings[-1]
        text = clean(card.get_text(" ", strip=True))
        employment = employment_from_text(text) or employment_from_text(title)
        if employment is None:
            continue

        native = stable_native_id(url, f"{company}|{title}")
        jobs.setdefault(
            f"taqe:{native}",
            Job(
                source="taqe",
                source_job_id=f"taqe:{native}",
                company=company,
                title=title,
                location=location_from_text(text) or _location(card),
                url=url,
                description=text,
                employment_type=employment,
                workplace_type=workplace_from_text(text),
                source_type="public_html",
                salary=salary_from_text(text),
                metadata={
                    "platform": "taqe",
                    "coverage": "public_national_catalog",
                },
            ),
        )

    return list(jobs.values())


def collect_taqe(config: dict) -> list[Job]:
    url = config.get("list_url") or DEFAULT_URL
    jobs = _parse(get_text(url), url)
    configured = int(config.get("max_jobs", 0) or 0)
    if configured > 0:
        jobs = jobs[:configured]

    if config.get("show_incremental_stats", True):
        known = set(config.get("known_source_job_ids") or ())
        ids = {job.source_job_id for job in jobs}
        print(
            f"[FAST] TAQE: {len(ids & known)} conhecidos | "
            f"{len(ids - known)} novos | 1 request"
        )

    return jobs
