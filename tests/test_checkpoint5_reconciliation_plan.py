"""CP5 reconciliation plan: deterministic, read-only unit tests."""
import pytest
from tools.plan_postgres_reconciliation import build_reconciliation_plan

def posting(source, id, *, raw="h", active=True, op=None, miss=0, changed="2026-10-02T00:00:00Z"):
    return dict(source=source, source_job_id=id, opportunity_id=op or id,
                raw_hash=raw, processing_version="v1", is_active=active,
                miss_count=miss, last_changed_at=changed,
                last_seen_at=changed, missing_since=None, inactive_at=None)

def test_union_and_preservation():
    p=build_reconciliation_plan([posting("x","1"),posting("x","2",active=False)],
                                [posting("x","1"),posting("y","3")])
    assert p["postings"] == dict(sqlite=2,postgres=2,shared=1,
        sqlite_only_insert_candidates=1,postgres_only_preserve=1,union_if_preserved=3)
    assert p["read_only"] and not p["apply_supported"] and p["safe_automatic_updates"]==0

def test_content_conflict_does_not_authorize_writes():
    p=build_reconciliation_plan(
       [posting("x","1",raw="new",changed="2026-10-10T00:00:00Z")],
       [posting("x","1",raw="old")])
    assert p["shared_posting_conflicts"]["raw_hash_mismatch"]==1
    assert p["timestamp_evidence_not_authority"]["sqlite_content_timestamp_newer"]==1
    assert p["safe_automatic_updates"]==0

def test_lifecycle_review():
    p=build_reconciliation_plan([posting("x","1",active=False,miss=3)],
                                [posting("x","1")])
    assert p["shared_posting_conflicts"]["active_status_mismatch"]==1
    assert p["shared_posting_conflicts"]["lifecycle_review"]==1

def test_association_collision():
    p=build_reconciliation_plan([posting("x","new",op="shared")],
                                [posting("y","old",op="shared")])
    assert p["shared_posting_conflicts"]["insert_opportunity_id_collision_review"]==1

def test_score_payload_and_intents():
    p=build_reconciliation_plan(
        [posting("x","1")],[posting("x","1")],
        sqlite_scores=[dict(opportunity_id="1",course_id="cs",score=80)],
        postgres_scores=[dict(opportunity_id="1",course_id="cs",score=0)],
        sqlite_intents=[dict(opportunity_id="1",intent_id="internship")],
        postgres_intents=[],
        sqlite_payloads=[dict(source="x",source_job_id="1",scores='{"cs":80}')],
        postgres_payloads=[dict(source="x",source_job_id="1",scores='{"cs":80}')])
    assert p["derived_differences"]["course_scores_mismatch"]==1
    assert p["derived_differences"]["intents_mismatch"]==1
    assert p["derived_differences"]["postgres_scores_vs_payload_mismatch"]==1

def test_determinism_and_duplicate_rejection():
    a=[posting("b","2"),posting("a","1")]
    b=[posting("a","1"),posting("b","2")]
    assert build_reconciliation_plan(a,b)==build_reconciliation_plan(b,a)
    with pytest.raises(ValueError,match="Identidade duplicada"):
        build_reconciliation_plan(a+a,[])
    with pytest.raises(ValueError,match="max_samples"):
        build_reconciliation_plan([],[],max_samples=0)
