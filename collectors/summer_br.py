"""Dedicated discovery for Brazilian vacation/summer opportunities.

The global collectors remain broad. This module adds targeted passes for a rare
category so Estágio de Férias / Estágio de Verão is not buried behind thousands
of ordinary internship results.
"""

from __future__ import annotations

from typing import Iterable

from collectors import gupy_global as gupy
from collectors import jobs99
from collectors.vagas_com import collect_vagas_com
from models.job import Job
from processing.text import normalize


SUMMER_INTERNSHIP_TERMS = (
    "estagio de ferias",
    "programa de estagio de ferias",
    "estagio de verao",
    "programa de estagio de verao",
    "programa de ferias",
    "programa de verao",
    "summer internship",
    "summer intern",
    "vacation internship",
    "vacation intern",
)

SEASONAL_TERMS = (
    "summer job",
    "trabalho de ferias",
    "trabalho temporario de ferias",
    "trabalho temporario de verao",
    "vaga de ferias",
    "vaga temporaria de ferias",
    "vaga temporaria de verao",
)

DISCOVERY_TERMS = SUMMER_INTERNSHIP_TERMS + SEASONAL_TERMS


def collect_gupy_summer_br(config: dict | None = None) -> list[Job]:
    cfg = config or {}
    page_size = max(10, min(int(cfg.get("page_size", 100)), 100))
    native_pages = max(1, min(int(cfg.get("summer_native_pages", 8)), 20))
    keyword_pages = max(1, min(int(cfg.get("summer_keyword_pages", 3)), 8))
    terms = tuple(cfg.get("summer_terms") or DISCOVERY_TERMS)

    found: list[Job] = []

    # Gupy has a native summer vacancy type. Pull it deeply first.
    found.extend(
        gupy._collect_segment(
            page_size=page_size,
            max_pages=native_pages,
            job_type="vacancy_type_summer",
        )
    )

    # Brazilian employers frequently publish vacation internships as ordinary
    # internship vacancies, so explicit keyword passes are still necessary.
    for term in terms:
        found.extend(
            gupy._collect_segment(
                page_size=page_size,
                max_pages=keyword_pages,
                keyword=term,
            )
        )

    found = gupy._deduplicate_gupy(found)
    result = []
    for job in found:
        if _is_brazil(job) and looks_like_vacation_opportunity(job):
            job.metadata["summer_discovery"] = True
            result.append(job)
    return result


def collect_99jobs_summer_br(config: dict | None = None) -> list[Job]:
    cfg = config or {}
    max_pages = max(1, min(int(cfg.get("jobs99_pages_per_term", 4)), 10))
    max_jobs = max(20, min(int(cfg.get("jobs99_max_jobs", 700)), 2500))
    terms = tuple(cfg.get("summer_terms") or DISCOVERY_TERMS)
    found: dict[str, Job] = {}

    for term in terms:
        if len(found) >= max_jobs:
            break
        jobs99._collect_pages(
            found,
            lambda page, term=term: jobs99._search_page_url(term, page),
            max_pages,
            max_jobs,
        )

    out = []
    for job in found.values():
        if looks_like_vacation_opportunity(job):
            job.metadata["summer_discovery"] = True
            out.append(job)
    return out[:max_jobs]


def collect_vagas_summer_br(config: dict | None = None) -> list[Job]:
    cfg = config or {}
    max_per_query = max(10, min(int(cfg.get("vagas_max_jobs_per_query", 80)), 100))
    terms = tuple(cfg.get("summer_terms") or DISCOVERY_TERMS)
    found: dict[str, Job] = {}

    for term in terms:
        for job in collect_vagas_com(term, max_per_query):
            if not looks_like_vacation_opportunity(job):
                continue
            job.metadata["summer_discovery"] = True
            job.metadata["summer_discovery_term"] = term
            found[f"{job.source}:{job.source_job_id}"] = job

    return list(found.values())


def looks_like_vacation_opportunity(job: Job) -> bool:
    if normalize(str((job.metadata or {}).get("gupy_job_type") or "")) == "vacancy_type_summer":
        return True

    text = normalize(" ".join([
        job.title or "",
        job.employment_type or "",
        job.description or "",
    ]))
    padded = f" {text} "
    return any(f" {normalize(term)} " in padded for term in DISCOVERY_TERMS)


def _is_brazil(job: Job) -> bool:
    metadata = job.metadata or {}
    country = normalize(str(metadata.get("gupy_country") or ""))
    resolved = str(metadata.get("resolved_country") or "").strip().upper()
    location = normalize(job.location or "")
    return (
        resolved == "BR"
        or country in {"br", "brasil", "brazil"}
        or " brasil" in f" {location}"
        or " brazil" in f" {location}"
    )
