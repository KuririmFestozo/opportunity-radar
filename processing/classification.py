import re

from config.catalogs import COURSES, INTENTS
from models.job import Job
from processing.text import normalize, contains_any


def classify_job(job: Job) -> Job:
    title = normalize(job.title)
    body = normalize(job.description)
    employment = normalize(job.employment_type or "")
    whole = f"{title} {body} {employment}"
    title_employment = f"{title} {employment}"

    job.course_scores = {
        course_id: _course_affinity(title, whole, cfg)
        for course_id, cfg in COURSES.items()
    }

    detected = []

    # Gupy exposes structured vacancy types. Prefer them over text inference
    # whenever available so generic titles such as "Programa 2027" are not
    # lost.
    gupy_type = str(job.metadata.get("gupy_job_type") or "").strip().lower()
    gupy_intents = {
        "vacancy_type_internship": ["internship"],
        "vacancy_type_summer": ["summer_internship", "internship"],
        "vacancy_type_trainee": ["trainee"],
        "vacancy_type_apprentice": ["apprentice"],
    }
    detected.extend(gupy_intents.get(gupy_type, []))

    # Strong signal: title / explicit employment type.
    for intent_id, cfg in INTENTS.items():
        if contains_any(title_employment, cfg["terms"]):
            detected.append(intent_id)

    # Summer can appear with a year between words.
    if (
        re.search(r"\bsummer\b.{0,100}\b(intern|internship)\b", title_employment)
        or re.search(r"\b(intern|internship)\b.{0,100}\bsummer\b", title_employment)
    ):
        detected += ["summer_internship", "internship"]

    # Brazilian equivalent of a summer internship.
    if any(
        phrase in title_employment
        for phrase in [
            "estagio de verao",
            "programa de estagio de verao",
            "estagio de ferias",
            "programa de estagio de ferias",
            "programa de ferias",
        ]
    ):
        detected += ["summer_internship", "internship"]

    if re.search(r"\bco[\s-]?op\b|\bcoop\b", title_employment):
        detected.append("co_op")

    # Distinctive phrases may safely be detected in description.
    distinctive = {
        "summer_internship": [
            "summer internship",
            "summer intern",
            "estagio de verao",
            "programa de estagio de verao",
            "estagio de ferias",
            "programa de estagio de ferias",
            "programa de ferias",
        ],
        "seasonal_job": [
            "summer job",
            "seasonal job",
            "seasonal work",
            "trabalho de ferias",
            "trabalho temporario de verao",
        ],
        "co_op": ["co-op", "co op", "coop"],
        "trainee": [
            "programa trainee",
            "programa de trainee",
            "graduate program",
            "graduate programme",
        ],
        "entry_level": [
            "new grad",
            "new graduate",
            "early career",
        ],
        "research": [
            "research internship",
            "research intern",
            "undergraduate research",
            "iniciacao cientifica",
        ],
        "apprentice": [
            "jovem aprendiz",
            "apprenticeship",
        ],
    }

    for intent_id, terms in distinctive.items():
        if contains_any(whole, terms):
            detected.append(intent_id)

    job.detected_intents = _unique(detected)
    return job


def _course_affinity(title: str, whole: str, cfg: dict) -> int:
    core_title = contains_any(title, cfg["core_terms"])
    core_all = contains_any(whole, cfg["core_terms"])
    related_title = contains_any(title, cfg["related_terms"])
    related_all = contains_any(whole, cfg["related_terms"])

    score = 0

    if core_title:
        score += 70
    elif core_all:
        score += min(60, 35 + 7 * len(set(core_all)))

    if related_title:
        score += min(30, 12 + 5 * len(set(related_title)))
    elif related_all:
        score += min(25, 6 + 3 * len(set(related_all)))

    return min(100, score)


def _unique(values):
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
