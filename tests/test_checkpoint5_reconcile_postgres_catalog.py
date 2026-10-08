import pytest

from models.job import Job
from storage.postgres_repository import _association_plan
from tools.reconcile_postgres_catalog import (
    guard_apply,
    summarize_plan,
)


def _row(source, source_job_id, first_seen):
    job = Job(
        source=source,
        source_job_id=source_job_id,
        company="Example Corp",
        title="Engineering Intern",
        location="São Carlos, SP",
        url="https://careers.example.com/jobs/77777",
        description="Engineering internship",
        published_at="2026-09-20",
    )
    return {
        "source": source,
        "source_job_id": source_job_id,
        "opportunity_id": "00000000-0000-0000-0000-000000000001"
        if source == "alpha"
        else "00000000-0000-0000-0000-000000000002",
        "association_method": "identity",
        "normalized_job_json": job.to_dict(),
        "first_seen_at": first_seen,
        "last_changed_at": first_seen,
    }


def test_reconcile_dry_run_reports_cross_source_merge():
    rows = [
        _row("alpha", "a1", "2026-09-20T10:00:00+00:00"),
        _row("beta", "b1", "2026-09-21T10:00:00+00:00"),
    ]
    plan = _association_plan(rows)
    report = summarize_plan(rows, plan, current_opportunities=2)

    assert report["source_postings"] == 2
    assert report["cross_source_groups_expected"] == 1
    assert report["opportunities_expected"] == 1
    assert report["association_changes"] == 2
    assert report["orphan_or_redundant_opportunities"] == 1


def test_reconcile_apply_requires_expected_postings():
    report = {
        "source_postings": 2,
        "association_changes": 1,
        "orphan_or_redundant_opportunities": 0,
    }
    with pytest.raises(ValueError, match="expected-postings"):
        guard_apply(report, expected_postings=None, max_changes=100)
    with pytest.raises(ValueError, match="Quantidade de postings mudou"):
        guard_apply(report, expected_postings=3, max_changes=100)


def test_reconcile_apply_blocks_changes_over_safety_limit():
    report = {
        "source_postings": 2,
        "association_changes": 101,
        "orphan_or_redundant_opportunities": 0,
    }
    with pytest.raises(ValueError, match="limite de seguranca"):
        guard_apply(report, expected_postings=2, max_changes=100)


def test_reconcile_dry_run_no_candidates():
    rows = [_row("alpha", "a1", "2026-09-20T10:00:00+00:00")]
    plan = _association_plan(rows)
    report = summarize_plan(rows, plan, current_opportunities=1)

    assert report["opportunities_expected"] == 1
    assert report["association_changes"] == 0
    assert report["cross_source_groups_expected"] == 0
    guard_apply(report, expected_postings=1, max_changes=0)
