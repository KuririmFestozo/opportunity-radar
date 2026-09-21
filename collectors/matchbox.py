"""Matchbox Brasil public open programs."""
from __future__ import annotations

import re

from collectors.common import get_text
from collectors.public_early_career import (
    canonical_url,
    clean,
    normalize,
    soup,
    stable_native_id,
)
from models.job import Job

DEFAULT_URL = "https://matchboxbrasil.com/talentos/"


def _parse(html: str, base_url: str) -> list[Job]:
    doc = soup(html)
    jobs: dict[str, Job] = {}

    for link in doc.find_all("a", href=True):
        label = clean(link.get_text(" ", strip=True))
        normalized = normalize(label)

        if "inscricoes encerradas" in normalized:
            continue
        if (
            "inscreva se" not in normalized
            and "inscreva-se" not in normalized
        ):
            continue

        title = re.sub(r"(?i)\s*inscreva-se\s*$", "", label).strip()
        ntitle = normalize(title)

        if "trainee" in ntitle:
            employment = "trainee"
        elif "estagio" in ntitle:
            employment = "internship"
        elif "aprendiz" in ntitle:
            employment = "apprentice"
        else:
            continue

        url = canonical_url(base_url, link.get("href"))
        native = stable_native_id(url, title)

        jobs.setdefault(
            f"matchbox:{native}",
            Job(
                source="matchbox",
                source_job_id=f"matchbox:{native}",
                company="Matchbox / empresa anunciante",
                title=title,
                location="Brasil",
                url=url,
                employment_type=employment,
                source_type="public_html",
                metadata={
                    "platform": "matchbox",
                    "coverage": "public_open_programs",
                },
            ),
        )

    return list(jobs.values())


def collect_matchbox(config: dict) -> list[Job]:
    url = config.get("list_url") or DEFAULT_URL
    jobs = _parse(get_text(url), url)
    configured = int(config.get("max_jobs", 0) or 0)
    if configured > 0:
        jobs = jobs[:configured]
    if config.get("show_incremental_stats", True):
        print(f"[PUBLIC] Matchbox: {len(jobs)} programas públicos abertos")
    return jobs
