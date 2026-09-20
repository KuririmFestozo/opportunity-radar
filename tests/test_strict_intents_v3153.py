from models.job import Job
from models.profile import SearchProfile
from processing.matching import INTENT_COMPATIBILITY, match_job


def _profile(intent_ids):
    return SearchProfile(
        id="test",
        name="test",
        course_ids=[],
        intent_ids=intent_ids,
        preferred_workplace_types=[],
        preferred_countries=[],
        minimum_score=0,
    )


def _job(intents):
    return Job(
        source="test",
        source_job_id="1",
        company="Empresa",
        title="Vaga",
        location="",
        url="https://example.com/1",
        detected_intents=list(intents),
    )


def test_plain_internship_is_not_summer():
    assert "internship" not in INTENT_COMPATIBILITY["summer_internship"]
    assert not match_job(
        _job(["internship"]),
        _profile(["summer_internship", "seasonal_job"]),
    ).eligible


def test_explicit_summer_is_summer():
    assert match_job(
        _job(["summer_internship"]),
        _profile(["summer_internship", "seasonal_job"]),
    ).eligible


def test_generic_internship_accepts_summer_and_coop():
    assert match_job(_job(["summer_internship"]), _profile(["internship"])).eligible
    assert match_job(_job(["co_op"]), _profile(["internship"])).eligible


def test_coop_and_research_are_strict():
    assert "internship" not in INTENT_COMPATIBILITY["co_op"]
    assert "internship" not in INTENT_COMPATIBILITY["research"]
