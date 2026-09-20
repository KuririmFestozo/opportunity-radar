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
    for i, line in enumerate(lines):
        if not re.fullmatch(r"(?:Superior|Técnico|Tecnico|Médio|Medio|Pós-Graduação|Pos-Graduacao)", line, re.I):
            continue
        window = lines[max(0, i - 4): i + 1]
        joined = " | ".join(window)
        salary = salary_from_text(joined)
        if not salary:
            continue
        title = window[-3] if len(window) >= 3 else ""
        company = window[-4] if len(window) >= 4 else "Confidencial"
        if not title or re.search(r"R\$", title):
            continue
        raw = normalize(f"{company}|{title}|{city}|{salary}|{line}")
        native = hashlib.sha1(raw.encode()).hexdigest()[:18]
        job = Job(
            source="superestagios",
            source_job_id=f"superestagios:{native}",
            company=company,
            title=title,
            location=city,
            url=url,
            employment_type="internship",
            source_type="public_html",
            salary=salary,
            metadata={"platform": "superestagios", "coverage": "partial_public_seo", "id_strategy": "sha1(public_card)", "education_level": line},
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
    return list(jobs.values())[: max(1, min(int(config.get("max_jobs", 500)), 5000))]
