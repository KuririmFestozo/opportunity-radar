from config.profiles import PROFILES
from models.job import Job
from processing.classification import classify_job
from processing.geolocation import enrich_job_location
from processing.matching import match_job


def test_regular_engineer_is_not_internship_from_description_boilerplate():
    job = Job(
        "test", "1", "Forge", "Electrical Engineer", "Oak Ridge, TN", "https://example.com",
        description="We have interns and internship programs across the company.",
    )
    classify_job(job)
    assert "internship" not in job.detected_intents


def test_us_job_is_excluded_from_br_profile():
    job = Job(
        "test", "2", "Persona", "Electrical Engineering Internship", "Houston, TX", "https://example.com"
    )
    classify_job(job)
    enrich_job_location(job)
    match = match_job(job, PROFILES["electrical_internship_br"])
    assert job.metadata.get("resolved_country") == "US"
    assert match.eligible is False
    assert any("país fora" in reason for reason in match.reasons)


def test_brazil_job_remains_eligible_when_relevant():
    job = Job(
        "test", "3", "Empresa BR", "Estágio em Engenharia Elétrica", "Campinas - SP", "https://example.com"
    )
    classify_job(job)
    enrich_job_location(job)
    match = match_job(job, PROFILES["electrical_internship_br"])
    assert job.metadata.get("resolved_country") == "BR"
    assert match.eligible is True
