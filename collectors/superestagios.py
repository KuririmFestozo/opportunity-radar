"""Super Estágios public SEO parser; disabled by default."""
from __future__ import annotations

import hashlib
import re

from collectors.common import get_text
from collectors.public_early_career import clean, normalize, salary_from_text, soup
from models.job import Job


def _parse_city_page(html: str, url: str, city: str = "") -> list[Job]:
    doc = soup(html)
    text = (doc.find("main") or doc).get_text("\n", strip=True)
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    jobs = {}

    level_re = re.compile(
        r"(?:Superior|Técnico|Tecnico|Médio|Medio|Pós-Graduação|Pos-Graduacao)",
        re.I,
    )
    hours_re = re.compile(r"^\d+\s+horas?$", re.I)

    for i, level in enumerate(lines):
        if not level_re.fullmatch(level):
            continue

        salary_idx = None
        salary = None
        for j in range(i - 1, max(-1, i - 4), -1):
            candidate = salary_from_text(lines[j])
            if candidate:
                salary_idx = j
                salary = candidate
                break
        if salary_idx is None or not salary:
            continue

        hours_idx = None
        for j in range(salary_idx - 1, max(-1, salary_idx - 4), -1):
            if hours_re.fullmatch(lines[j]):
                hours_idx = j
                break
        if hours_idx is None or hours_idx < 3:
            continue

        location = city or lines[hours_idx - 1]
        title = lines[hours_idx - 2]
        company = lines[hours_idx - 3]

        if (
            not title
            or hours_re.fullmatch(title)
            or salary_from_text(title)
            or level_re.fullmatch(title)
        ):
            continue

        raw = normalize(f"{company}|{title}|{location}|{salary}|{level}")
        native = hashlib.sha1(raw.encode()).hexdigest()[:18]

        job = Job(
            source="superestagios",
            source_job_id=f"superestagios:{native}",
            company=company or "Confidencial",
            title=title,
            location=location,
            url=url,
            employment_type="internship",
            source_type="public_html",
            salary=salary,
            metadata={
                "platform": "superestagios",
                "coverage": "partial_public_seo",
                "id_strategy": "sha1(public_card)",
                "education_level": level,
                "workload": lines[hours_idx],
            },
        )
        jobs.setdefault(job.source_job_id, job)

    return list(jobs.values())


def collect_superestagios(config: dict) -> list[Job]:
    pages = config.get("list_pages") or []
    if not pages:
        print("[SKIP] Super Estágios: sem páginas públicas configuradas; collector permanece conservador.")
        return []
    jobs = {}
    for page in pages:
        url = page["url"] if isinstance(page, dict) else str(page)
        city = page.get("city", "") if isinstance(page, dict) else ""
        for job in _parse_city_page(get_text(url), url, city):
            jobs.setdefault(job.source_job_id, job)
    out = list(jobs.values())
    configured = int(config.get("max_jobs", 0) or 0)
    return out[:configured] if configured > 0 else out
