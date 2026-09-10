from models.job import Job
from processing.classification import classify_job
from collectors.summer_br import looks_like_vacation_opportunity, _is_brazil


def make_job(title, description="", *, country="Brasil", job_type=None):
    metadata = {"gupy_country": country}
    if job_type:
        metadata["gupy_job_type"] = job_type
    return Job(
        source="test",
        source_job_id=title,
        company="Empresa",
        title=title,
        location="São Paulo, São Paulo, Brasil" if country == "Brasil" else "New York, USA",
        url="https://example.com",
        description=description,
        metadata=metadata,
    )


def test_programa_de_verao_is_summer_internship():
    job = make_job("Programa de Verão 2027 - Engenharia")
    classify_job(job)
    assert "summer_internship" in job.detected_intents
    assert "internship" in job.detected_intents


def test_vacation_internship_is_summer_internship():
    job = make_job("Vacation Internship - Technology")
    classify_job(job)
    assert "summer_internship" in job.detected_intents


def test_temporary_vacation_work_is_seasonal():
    job = make_job("Trabalho temporário de férias - Janeiro")
    classify_job(job)
    assert "seasonal_job" in job.detected_intents


def test_native_gupy_summer_is_accepted_even_with_generic_title():
    job = make_job("Programa 2027", job_type="vacancy_type_summer")
    assert looks_like_vacation_opportunity(job)
    assert _is_brazil(job)


def test_generic_internship_is_not_promoted_to_summer():
    job = make_job("Estágio em Engenharia Elétrica")
    assert not looks_like_vacation_opportunity(job)


def test_non_brazil_job_is_not_brazil():
    job = make_job("Summer Internship", country="United States")
    assert not _is_brazil(job)
