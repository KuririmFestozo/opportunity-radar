from models.job import Job
from storage.postgres_repository import _association_plan
from storage.unified_schema import _stable_opportunity_id


URL = "https://careers.example.com/jobs/77777"


def _row(
    source: str,
    source_job_id: str,
    *,
    first_seen: str,
    opportunity_id: str | None = None,
    association_method: str = "identity",
    url: str = URL,
    title: str = "Engineering Intern",
):
    job = Job(
        source=source,
        source_job_id=source_job_id,
        company="Example Corp",
        title=title,
        location="São Carlos, SP",
        url=url,
        description="Engineering internship",
        published_at="2026-09-20",
        employment_type="internship",
        workplace_type="hybrid",
        course_scores={"electrical_engineering": 90},
        detected_intents=["internship"],
    )
    return {
        "source": source,
        "source_job_id": source_job_id,
        "opportunity_id": (
            opportunity_id
            or _stable_opportunity_id(source, source_job_id)
        ),
        "association_method": association_method,
        "associated_at": first_seen,
        "normalized_job_json": job.to_dict(),
        "first_seen_at": first_seen,
        "last_changed_at": first_seen,
    }


def test_cp5d_plan_merges_compatible_cross_source_postings_on_oldest_anchor():
    first = _row(
        "gupy_global",
        "gupy:77777",
        first_seen="2026-09-20T10:00:00+00:00",
    )
    second = _row(
        "workday",
        "company:77777",
        first_seen="2026-09-21T10:00:00+00:00",
    )

    plan = _association_plan([first, second])

    anchor = _stable_opportunity_id("gupy_global", "gupy:77777")
    assert len(plan["groups"]) == 1
    assert plan["desired_by_key"][("gupy_global", "gupy:77777")] == (
        anchor,
        "conservative_url",
    )
    assert plan["desired_by_key"][("workday", "company:77777")] == (
        anchor,
        "conservative_url",
    )
    assert len(plan["link_updates"]) == 2
    assert anchor in plan["affected_opportunity_ids"]


def test_cp5d_plan_keeps_conflicting_publications_separate():
    first = _row(
        "gupy_global",
        "gupy:77777",
        first_seen="2026-09-20T10:00:00+00:00",
    )
    second = _row(
        "workday",
        "company:77777",
        first_seen="2026-09-21T10:00:00+00:00",
        title="Different Engineering Intern",
    )

    plan = _association_plan([first, second])

    assert len(plan["groups"]) == 2
    assert plan["desired_by_key"][("gupy_global", "gupy:77777")][1] == "identity"
    assert plan["desired_by_key"][("workday", "company:77777")][1] == "identity"
    assert plan["link_updates"] == []


def test_cp5d_plan_splits_stale_merged_group_when_identity_evidence_changes():
    first_id = _stable_opportunity_id("gupy_global", "gupy:77777")
    second_id = _stable_opportunity_id("workday", "company:77777")
    first = _row(
        "gupy_global",
        "gupy:77777",
        first_seen="2026-09-20T10:00:00+00:00",
        opportunity_id=first_id,
        association_method="conservative_url",
    )
    second = _row(
        "workday",
        "company:77777",
        first_seen="2026-09-21T10:00:00+00:00",
        opportunity_id=first_id,
        association_method="conservative_url",
        url="https://careers.example.com/jobs/88888",
    )

    plan = _association_plan(
        [first, second],
        dirty_keys={("workday", "company:77777")},
    )

    assert len(plan["groups"]) == 2
    assert plan["desired_by_key"][("gupy_global", "gupy:77777")] == (
        first_id,
        "identity",
    )
    assert plan["desired_by_key"][("workday", "company:77777")] == (
        second_id,
        "identity",
    )
    assert set(plan["affected_opportunity_ids"]) == {first_id, second_id}
    assert len(plan["link_updates"]) == 2
