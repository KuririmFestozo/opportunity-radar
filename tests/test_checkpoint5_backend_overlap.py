from models.job import Job
from tools.validate_backend_overlap import compare_overlap


def _job(opportunity_id, *, title="Engineering Intern"):
    return Job(
        source="test",
        source_job_id=opportunity_id,
        company="Example",
        title=title,
        location="São Carlos",
        url=f"https://example.invalid/{opportunity_id}",
        metadata={
            "opportunity_id": opportunity_id,
            "opportunity_is_active": True,
            "source_references": [{
                "source": "test",
                "source_job_id": opportunity_id,
                "url": f"https://example.invalid/{opportunity_id}",
            }],
        },
    )


def test_overlap_allows_new_postgres_only_opportunities():
    older = [_job("a"), _job("b")]
    newer = [_job("a"), _job("b"), _job("c")]
    report = compare_overlap(older, newer)

    assert report["ok"] is True
    assert report["shared_count"] == 2
    assert report["shared_equal_count"] == 2
    assert report["postgres_only_count"] == 1
    assert report["sqlite_only_count"] == 0


def test_overlap_flags_shared_fields_that_changed():
    report = compare_overlap([_job("a")], [_job("a", title="Changed")])
    assert report["ok"] is False
    assert report["shared_mismatch_count"] == 1
    assert report["different_fields_count"] == {"title": 1}
    assert report["shared_mismatch_sample"][0]["different_fields"] == ["title"]


def test_overlap_flags_missing_postgres_records():
    report = compare_overlap([_job("a"), _job("b")], [_job("b")])
    assert report["ok"] is False
    assert report["sqlite_only_count"] == 1
    assert report["shared_count"] == 1


def test_overlap_rejects_no_shared_opportunities():
    report = compare_overlap([_job("a")], [_job("b")])
    assert report["ok"] is False
    assert report["shared_count"] == 0


def test_overlap_both_empty_is_not_a_success():
    report = compare_overlap([], [])
    assert report["ok"] is False
