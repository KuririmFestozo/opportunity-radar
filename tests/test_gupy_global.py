from collectors.gupy_global import _build_params, job_from_item
from processing.classification import classify_job


def test_gupy_global_builds_native_type_query():
    params = _build_params(
        offset=100,
        limit=999,
        job_type="vacancy_type_summer",
    )
    assert params["offset"] == 100
    assert params["limit"] == 100
    assert params["sortBy"] == "publishedDate"
    assert params["type"] == "vacancy_type_summer"
    assert "jobName" not in params


def test_gupy_global_maps_portal_item():
    job = job_from_item(
        {
            "id": 12345,
            "name": "Programa 2027",
            "careerPageName": "Empresa Exemplo",
            "city": "Campinas",
            "state": "São Paulo",
            "country": "Brazil",
            "jobUrl": "https://empresa.gupy.io/jobs/12345",
            "publishedDate": "2026-09-09T12:00:00.000Z",
            "workplaceType": "hybrid",
            "type": "vacancy_type_summer",
            "description": "Programa para estudantes de engenharia.",
        }
    )
    assert job is not None
    assert job.source == "gupy_global"
    assert job.source_job_id == "12345"
    assert job.company == "Empresa Exemplo"
    assert job.location == "Campinas, São Paulo, Brazil"
    assert job.workplace_type == "hybrid"
    assert job.metadata["resolved_country"] == "BR"
    assert job.metadata["gupy_job_type"] == "vacancy_type_summer"


def test_structured_gupy_summer_type_beats_generic_title():
    job = job_from_item(
        {
            "id": 777,
            "name": "Programa 2027",
            "careerPageName": "Empresa",
            "jobUrl": "https://empresa.gupy.io/jobs/777",
            "type": "vacancy_type_summer",
        }
    )
    assert job is not None
    classify_job(job)
    assert "summer_internship" in job.detected_intents
    assert "internship" in job.detected_intents


def test_remote_country_is_kept_even_without_city():
    job = job_from_item(
        {
            "id": 9,
            "name": "Software Intern",
            "careerPageName": "Empresa",
            "country": "Brazil",
            "jobUrl": "https://empresa.gupy.io/jobs/9",
            "workplaceType": "remote",
            "type": "vacancy_type_internship",
        }
    )
    assert job is not None
    assert job.location == "Brazil - Remote"
    assert job.metadata["resolved_country"] == "BR"


def test_gupy_global_builds_city_targeted_query():
    params = _build_params(
        offset=0,
        limit=100,
        city="São Carlos",
        job_type="vacancy_type_internship,vacancy_type_summer",
    )
    assert params["city"] == "São Carlos"
    assert params["type"] == "vacancy_type_internship,vacancy_type_summer"
