from __future__ import annotations

import hashlib
import re

from collectors.common import get_text
from collectors.public_early_career import canonical_url, clean, normalize, soup, stable_native_id
from models.job import Job


DEFAULT_URL = "https://www.ciadeestagios.com.br/vagas-de-estagio/"


def _company_from_title(title: str) -> str:
    value = re.sub(
        r"(?i)^programa\s+(?:de\s+)?(?:estágio|estagio|trainee|jovem\s+aprendiz)\s*",
        "",
        title,
    )
    value = re.sub(r"\b20\d{2}\b", "", value)
    value = clean(value.strip(" -|"))
    return value or "Companhia de Estágios / empresa anunciante"


def _native(title: str, url: str) -> str:
    native = stable_native_id(url, title)
    if not native.startswith("h-"):
        return native
    raw = normalize(title) + "|" + url
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:18]


def _is_program_heading(value: str) -> bool:
    value = normalize(value)
    return (
        "programa de estagio" in value
        or "programa de trainee" in value
        or "programa jovem aprendiz" in value
        or "programa de jovem aprendiz" in value
        or value.startswith("jovem aprendiz ")
    )


def _find_action(heading):
    for node in heading.find_all_next(["a", "button", "h2", "h3"], limit=20):
        if node is heading:
            continue

        label = clean(node.get_text(" ", strip=True))
        if node.name in {"h2", "h3"} and _is_program_heading(label):
            break

        normalized = normalize(label)
        if "inscricoes encerradas" in normalized:
            return "closed", node
        if (
            "fazer inscricao" in normalized
            or "inscreva se" in normalized
            or "fazer cadastro" in normalized
            or normalized == "participar"
        ):
            return "open", node

    return None, None


def _parse(html: str, base_url: str) -> list[Job]:
    doc = soup(html)
    jobs = {}

    for heading in doc.find_all(["h2", "h3"]):
        title = clean(heading.get_text(" ", strip=True))
        if not _is_program_heading(title):
            continue

        status, action = _find_action(heading)
        if status != "open" or action is None:
            continue

        href = clean(action.get("href")) if getattr(action, "get", None) else ""
        if not href:
            parent = heading.parent
            nearby = parent.find("a", href=True) if parent else None
            href = clean(nearby.get("href")) if nearby else ""

        url = canonical_url(base_url, href) if href else base_url
        native = _native(title, url)

        ntitle = normalize(title)
        employment = (
            "trainee"
            if "trainee" in ntitle
            else "apprentice"
            if "aprendiz" in ntitle
            else "internship"
        )

        job = Job(
            source="cia_estagios",
            source_job_id=f"cia_estagios:{native}",
            company=_company_from_title(title),
            title=title,
            location="",
            url=url,
            employment_type=employment,
            source_type="public_html",
            metadata={
                "platform": "cia_estagios",
                "coverage": "public_programs_only",
                "status": "open",
            },
        )
        jobs.setdefault(job.source_job_id, job)

    return list(jobs.values())


def collect_cia_estagios(config: dict) -> list[Job]:
    url = config.get("list_url") or DEFAULT_URL
    jobs = _parse(get_text(url), url)

    max_jobs = max(1, min(int(config.get("max_jobs", 200)), 1000))
    jobs = jobs[:max_jobs]

    if config.get("show_incremental_stats", True):
        print(
            f"[PUBLIC] Companhia de Estágios: "
            f"{len(jobs)} programas com inscrições abertas"
        )

    return jobs
