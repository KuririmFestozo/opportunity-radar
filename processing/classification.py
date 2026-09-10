import re

from config.catalogs import COURSES, INTENTS
from models.job import Job
from processing.text import normalize, contains_any
from processing.course_affinity import score_course_affinities


def classify_job(job: Job) -> Job:
    title = normalize(job.title)
    body = normalize(job.description)
    employment = normalize(job.employment_type or "")
    whole = f"{title} {body} {employment}"
    title_employment = f"{title} {employment}"

    job.course_scores, course_reasons = score_course_affinities(job)
    job.metadata["course_score_reasons"] = course_reasons

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

    # 99jobs exposes the opportunity level in its card. Prefer this
    # structured source signal over free-text inference.
    source_level = normalize(str(job.metadata.get("source_level") or ""))
    source_level_intents = {
        "estagio": ["internship"],
        "trainee": ["trainee"],
        "jovem aprendiz": ["apprentice"],
        "aprendiz": ["apprentice"],
        "junior": ["entry_level"],
    }
    detected.extend(source_level_intents.get(source_level, []))

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
            "programa de verao",
            "vacation internship",
            "vacation intern",
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
            "programa de verao",
            "vacation internship",
            "vacation intern",
        ],
        "seasonal_job": [
            "summer job",
            "seasonal job",
            "seasonal work",
            "trabalho de ferias",
            "trabalho temporario de verao",
            "trabalho temporario de ferias",
            "vaga de ferias",
            "vaga temporaria de ferias",
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



def _unique(values):
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
