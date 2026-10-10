from models.job import Job
from tools.diagnose_backend_overlap import diagnose


def _job(score):
    return Job(
        source="alpha", source_job_id="1", company="A", title="Engineer",
        location="SP", url="https://example.com/job/1",
        course_scores={"engineering": score},
        metadata={"opportunity_id": "id-1", "source_references": [{
            "source": "alpha", "source_job_id": "1",
            "url": "https://example.com/job/1"
        }], "opportunity_is_active": True},
    )


def _row(raw_hash, version, timestamp):
    return {
        "opportunity_id": "id-1", "source": "alpha", "source_job_id": "1",
        "raw_hash": raw_hash, "processing_version": version,
        "last_changed_at": timestamp,
    }


def test_diagnostic_recognizes_updated_posting_and_score_drop():
    result = diagnose(
        [_job(90)], [_job(0)],
        [_row("old", "3.14", "2026-09-20T00:00:00+00:00")],
        [_row("new", "3.15.4", "2026-10-02T00:00:00+00:00")],
    )
    assert result["mismatched_opportunities"] == 1
    counts = result["diagnostic_counts"]
    assert counts["raw_hash_changed"] == 1
    assert counts["processing_version_changed"] == 1
    assert counts["postgres_last_changed_newer"] == 1
    assert counts["course_scores_only"] == 1
    assert counts["scores_positive_sqlite_zero_postgres"] == 1
    assert "same_sources_hash_and_version" not in counts


def test_diagnostic_exposes_unexplained_score_mismatch():
    result = diagnose(
        [_job(90)], [_job(0)],
        [_row("same", "3.15.4", "2026-10-02T00:00:00+00:00")],
        [_row("same", "3.15.4", "2026-10-02T00:00:00+00:00")],
    )
    assert result["diagnostic_counts"]["same_sources_hash_and_version"] == 1
    assert result["mismatches_by_source"]["alpha"] == 1


def test_diagnostic_equal_snapshots_are_consistent():
    result = diagnose(
        [_job(90)], [_job(90)],
        [_row("same", "3.14", "2026-09-20T00:00:00+00:00")],
        [_row("same", "3.14", "2026-09-20T00:00:00+00:00")],
    )
    assert result["mismatched_opportunities"] == 0
    assert result["diagnostic_counts"] == {}
