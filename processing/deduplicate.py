import hashlib
import re
import unicodedata
from models.job import Job


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", (value or "").lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def fingerprint(job: Job) -> str:
    company, title, location = _norm(job.company), _norm(job.title), _norm(job.location)
    generic = {"vagas com", "99jobs", "gupy", "ciee empresa nao identificada"}
    if company and company not in generic:
        raw = f"{company}|{title}|{location}"
    else:
        raw = f"{job.source}|{job.source_job_id}|{title}|{location}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    unique = {}
    for job in jobs:
        key = fingerprint(job)
        if key not in unique:
            unique[key] = job
            continue
        old = unique[key]
        old_quality = len(old.description or "") + len(old.location or "")
        new_quality = len(job.description or "") + len(job.location or "")
        if new_quality > old_quality:
            unique[key] = job
    return list(unique.values())
