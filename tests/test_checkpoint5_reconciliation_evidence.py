"""Classification provenance and coverage evidence remain read-only."""
import pytest

from tools.plan_postgres_reconciliation import build_reconciliation_plan
from tools.reconciliation_evidence import classify_score_drift, compare_collection_scopes


def scope(source="workday", key="acme", *, coverage="complete", runs=2, at="2026-10-10T10:00:00Z"):
    return {
        "source": source, "scope_key": key, "successful_runs": runs,
        "last_full_run": runs if coverage == "complete" else 0,
        "last_coverage": coverage, "last_run_at": at,
    }


def posting(*, raw="unchanged"):
    return dict(
        source="workday", source_job_id="acme:1",
        opportunity_id="one", raw_hash=raw, processing_version="v1",
        first_seen_at="2026-10-01T10:00:00Z",
        last_seen_at="2026-10-10T10:00:00Z",
        last_changed_at="2026-10-01T10:00:00Z",
        last_checked_at="2026-10-10T10:00:00Z",
        is_active=True, miss_count=0, missing_since=None,
        inactive_at=None, association_method="identity",
    )


def score(course_id, value):
    return dict(opportunity_id="one", course_id=course_id, score=value)


def payload(scores):
    import json
    return dict(source="workday", source_job_id="acme:1",
                scores=json.dumps(scores, sort_keys=True))


def test_classification_distinguishes_missing_keys_from_different_values():
    report = classify_score_drift(
        {"one", "two"}, {"one", "two"},
        {"one": {"electrical": 55, "chemical": 0}, "two": {"cs": 70}},
        {"one": {"electrical": 55}, "two": {"cs": 35}},
    )
    assert report["shared_opportunities"] == 2
    assert report["metrics"]["course_scores_mismatch"] == 2
    assert report["metrics"]["sqlite_extra_course_keys_only"] == 1
    assert report["metrics"]["shared_course_values_only"] == 1
    assert report["courses_missing_from_postgres"] == {"chemical": 1}
    assert report["courses_with_changed_values"] == {"cs": 1}
    assert report["course_count_distribution"]["sqlite"] == {"1": 1, "2": 1}
    assert report["course_count_distribution"]["postgres"] == {"1": 2}
    assert report["automatic_reclassification_authorized"] is False


def test_classification_payload_consistency_and_mixed_difference():
    report = classify_score_drift(
        {"one"}, {"one"},
        {"one": {"a": 10, "b": 20}},
        {"one": {"a": 30, "c": 40}},
        {"one": {"a": 10, "b": 20}},
        {"one": {"a": 30, "c": 40}},
    )
    metrics = report["metrics"]
    assert metrics["mixed_course_differences"] == 1
    assert metrics["both_relational_match_own_payload"] == 1
    assert metrics["missing_postgres_course_cells"] == 1
    assert metrics["missing_sqlite_course_cells"] == 1
    assert metrics["changed_shared_course_values"] == 1


def test_scope_coverage_is_evidence_not_authorization():
    report = compare_collection_scopes(
        [scope(), scope("workday", "new")],
        [scope(at="2026-10-02T10:00:00Z"),
         scope("gupy_global", "historic", at="2026-10-02T10:00:00Z")],
        posting_sources=["workday", "gupy_global", "99jobs"],
    )
    assert report["shared_scopes"] == 1
    assert report["sqlite_only_scopes"] == 1
    assert report["postgres_only_scopes"] == 1
    assert report["metrics"]["sqlite_run_newer"] == 1
    assert report["metrics"]["sqlite_complete_run_newer_candidate_evidence"] == 1
    assert report["posting_sources_without_scope_history"] == ["99jobs"]
    assert not report["automatic_lifecycle_updates_authorized"]


def test_scope_unknown_and_duplicate_rejected():
    report = compare_collection_scopes(
        [scope(at=None)], [scope(at="2026-10-02T10:00:00Z")],
    )
    assert report["metrics"]["unknown_run_recency"] == 1
    with pytest.raises(ValueError, match="Escopo duplicado"):
        compare_collection_scopes([scope(), scope()], [])
    with pytest.raises(ValueError, match="max_samples"):
        compare_collection_scopes([], [], max_samples=0)


def test_cli_plan_function_includes_new_provenance_sections_without_writes():
    r = build_reconciliation_plan(
        [posting()], [posting()],
        sqlite_scores=[score("cs", 80), score("chemical", 0)],
        postgres_scores=[score("cs", 80)],
        sqlite_payloads=[payload({"cs": 80, "chemical": 0})],
        postgres_payloads=[payload({"cs": 80})],
        sqlite_scopes=[scope()],
        postgres_scopes=[scope(at="2026-10-02T10:00:00Z")],
    )
    assert r["derived_differences"]["course_scores_mismatch"] == 1
    provenance = r["classification_provenance"]
    assert provenance["metrics"]["sqlite_extra_course_keys_only"] == 1
    assert provenance["metrics"]["both_relational_match_own_payload"] == 1
    assert r["collection_scope_evidence"]["metrics"]["sqlite_run_newer"] == 1
    assert r["safe_automatic_updates"] == 0
    assert r["read_only"] and not r["apply_supported"]
