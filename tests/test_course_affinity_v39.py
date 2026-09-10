from models.job import Job
from processing.classification import classify_job


def make_job(title, description=""):
    return Job(
        source="test",
        source_job_id=title,
        company="Example",
        title=title,
        location="",
        url="https://example.com",
        description=description,
    )


def test_explicit_electrical_title_is_very_high():
    job = make_job("Principal Engineer, Electrical")
    classify_job(job)
    assert job.course_scores["electrical_engineering"] >= 90


def test_explicit_mechanical_title_is_very_high():
    job = make_job("Engineer II, Mechanical")
    classify_job(job)
    assert job.course_scores["mechanical_engineering"] >= 90


def test_computer_vision_is_strong_for_cs_and_data_science():
    job = make_job("Computer Vision Engineer (C++)")
    classify_job(job)
    assert job.course_scores["computer_science"] >= 70
    assert job.course_scores["data_science"] >= 70


def test_structural_engineering_intern_is_civil_when_not_aerospace():
    job = make_job("Structural Engineering Intern (Summer 2027)", "Work on bridges and infrastructure projects.")
    classify_job(job)
    assert job.course_scores["civil_engineering"] >= 70


def test_aerospace_structural_analysis_does_not_look_civil():
    job = make_job(
        "Engineer II, Structural Analysis",
        "Analyze aircraft structures, UAV loads and aerospace composite materials.",
    )
    classify_job(job)
    assert job.course_scores["mechanical_engineering"] >= 70
    assert job.course_scores["civil_engineering"] < 35


def test_finance_role_is_admin_not_engineering_from_boilerplate():
    job = make_job(
        "Finance Intern",
        "Partner with finance teams. Our company also employs electrical engineering, mechanical engineering and computer science teams.",
    )
    classify_job(job)
    assert job.course_scores["administration"] >= 70
    assert job.course_scores["electrical_engineering"] < 35
    assert job.course_scores["computer_science"] < 35


def test_explicit_degree_requirement_is_strong_even_with_generic_title():
    job = make_job(
        "Engineering Intern",
        "Candidates must be students currently pursuing a degree in Electrical Engineering or Electronics Engineering.",
    )
    classify_job(job)
    assert job.course_scores["electrical_engineering"] >= 85


def test_business_development_is_related_to_admin_but_not_near_certain():
    job = make_job("Business Development & Sales Lead")
    classify_job(job)
    assert 70 <= job.course_scores["administration"] < 90


def test_media_production_does_not_match_production_engineering():
    job = make_job("Estágio Produção Digital e Audiovisual")
    classify_job(job)
    assert job.course_scores["production_engineering"] < 35


def test_reasons_are_saved_in_metadata():
    job = make_job("Electrical Engineer I")
    classify_job(job)
    reasons = job.metadata["course_score_reasons"]["electrical_engineering"]
    assert reasons
    assert any("título" in reason for reason in reasons)
