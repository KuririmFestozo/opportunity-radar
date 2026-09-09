from models.job import Job
from processing.classification import classify_job


def test_generic_course_classification():
    job = Job("test", "1", "X", "Mechanical Engineering Intern", "", "https://example.com")
    classify_job(job)
    assert job.course_scores["mechanical_engineering"] >= 70
    assert "internship" in job.detected_intents
