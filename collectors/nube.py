from __future__ import annotations

import re

from collectors.common import get_text
from collectors.public_early_career import clean, normalize, salary_from_text, soup, workplace_from_text
from models.job import Job


DEFAULT_URL = "https://www.nube.com.br/estudantes/vagas/busca-avancada-saida"
_TITLE_CODE = re.compile(r"^(.+?)\s*-\s*(\d{4,})$")
_LOCATION = re.compile(r"^(.+?)\s*\|\s*([A-Z]{2})$")


def _lines(html: str) -> list[str]:
    return [clean(value) for value in soup(html).stripped_strings if clean(value)]


def _parse(html: str, base_url: str) -> list[Job]:
    lines = _lines(html)
    starts = []

    for index, line in enumerate(lines):
        match = _TITLE_CODE.match(line)
        if match:
            starts.append((index, match.group(1).strip(), match.group(2)))

    jobs = {}

    for pos, (index, title, native) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else min(len(lines), index + 40)
        block = lines[index + 1:end]
        normalized = [normalize(value) for value in block]

        if any("vaga de aprendiz" in value for value in normalized):
            employment = "apprentice"
        elif any("vaga de estagio" in value for value in normalized):
            employment = "internship"
        else:
            continue

        location = ""
        for value in block:
            match = _LOCATION.match(value)
            if match:
                location = f"{match.group(1).strip()}, {match.group(2)}"
                break

        workplace = None
        for value in block:
            workplace = workplace_from_text(value)
            if workplace:
                break

        salary = None
        for value in block:
            salary = salary_from_text(value)
            if salary:
                break

        job = Job(
            source="nube",
            source_job_id=f"nube:{native}",
            company="Nube / empresa anunciante",
            title=title,
            location=location,
            url=base_url,
            employment_type=employment,
            workplace_type=workplace,
            source_type="public_html",
            salary=salary,
            metadata={
                "platform": "nube",
                "native_code": native,
                "coverage": "public_search_cards",
                "detail_url_available": False,
            },
        )
        jobs.setdefault(job.source_job_id, job)

    return list(jobs.values())


def collect_nube(config: dict) -> list[Job]:
    url = config.get("list_url") or DEFAULT_URL
    jobs = _parse(get_text(url), url)

    max_jobs = max(1, min(int(config.get("max_jobs", 1500)), 10000))
    jobs = jobs[:max_jobs]

    if config.get("show_incremental_stats", True):
        known = set(config.get("known_source_job_ids") or ())
        ids = {job.source_job_id for job in jobs}
        print(
            f"[FAST] Nube: {len(ids & known)} conhecidos | "
            f"{len(ids - known)} novos | 1 request"
        )
        if not jobs:
            print(
                "[SKIP] Nube: a página pública abriu, mas nenhum card "
                "de vaga foi reconhecido."
            )

    return jobs
