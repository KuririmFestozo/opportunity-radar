"""Read-only tests for CP5 guarded additive stage (no remote DB required)."""

import sqlite3

import pytest

from tools.stage_postgres_additions import (
    _collect_inserts,
    _digest_remote,
    _run_additive,
    _sha256,
    _sqlite_connect,
    plan_additions,
)


def posting(source, job, opportunity, *, active=True, method="identity", hash="h"):
    return {
        "source": source, "source_job_id": job, "opportunity_id": opportunity,
        "association_method": method, "raw_hash": hash,
        "processing_version": "3.15.4", "is_active": active,
        "miss_count": 0, "last_changed_at": "2026-10-10 10:00:00+00",
    }


def test_preserves_postgres_and_classifies_additive_only():
    local = [
        posting("a", "1", "u1"),
        posting("a", "2", "u2", active=False),
        posting("a", "3", "u3"),
    ]
    remote = [posting("a", "1", "u1"), posting("b", "4", "u4")]
    plan = plan_additions(local, remote, ["u1", "u4"])
    assert plan["sqlite_only_postings"] == 2
    assert plan["candidate_source_keys"] == [("a", "2"), ("a", "3")]
    assert plan["candidate_insert_count"] == 2
    assert plan["candidate_inactive"] == 1
    assert plan["shared_postings_untouched"] == 1
    assert plan["postgres_only_postings_untouched"] == 1
    assert plan["blocked_insert_count"] == 0


def test_existing_id_and_cross_source_groups_never_inserted():
    local = [
        posting("a", "new", "pg_uuid"),
        posting("a", "x1", "group", method="conservative_url"),
        posting("b", "x2", "group", method="conservative_url"),
        posting("a", "unique", "new_uuid"),
        posting("b", "link", "link_uuid", method="manual"),
    ]
    result = plan_additions(local, [posting("pg", "old", "pg_uuid")], ["pg_uuid"])
    assert result["candidate_source_keys"] == [("a", "unique")]
    assert result["blocked_insert_count"] == 4
    assert result["blocked_by_reason"] == {
        "non_identity_association": 1,
        "opportunity_id_already_in_postgres": 1,
        "sqlite_cross_source_association": 2,
    }


def test_remote_fingerprint_changes_for_live_state_and_ids():
    remote = [posting("a", "1", "u1")]
    base = plan_additions([], remote, ["u1"])
    changes = [
        plan_additions([], [posting("a", "1", "u1", hash="new")], ["u1"]),
        plan_additions([], [posting("a", "1", "u1", active=False)], ["u1"]),
        plan_additions([], remote, ["u1", "u9"]),
    ]
    assert all(t["postgres_fingerprint"] != base["postgres_fingerprint"]
               for t in changes)
    assert base["postgres_fingerprint"] == plan_additions(
        [], list(reversed(remote)), ["u1"]
    )["postgres_fingerprint"]


def test_reject_invalid_duplicates_and_samples():
    row = posting("a", "id", "u1")
    with pytest.raises(ValueError, match="duplicate"):
        plan_additions([row, row], [], [])
    with pytest.raises(ValueError, match="max_samples"):
        plan_additions([], [], [], max_samples=0)


def _fixture_db(tmp_path):
    filename = tmp_path / "catalog.db"
    with sqlite3.connect(filename) as conn:
        conn.executescript("""
            CREATE TABLE opportunities(id TEXT PRIMARY KEY);
            CREATE TABLE source_postings(
                source TEXT, source_job_id TEXT, opportunity_id TEXT);
            CREATE TABLE opportunity_course_scores(
                opportunity_id TEXT, course_id TEXT, score INTEGER);
            CREATE TABLE opportunity_intents(
                opportunity_id TEXT, intent_id TEXT);
            CREATE TABLE discovery_state(source TEXT, source_job_id TEXT);
        """)
        conn.executemany("INSERT INTO opportunities(id) VALUES(?)", [("u1",), ("u2",)])
        conn.executemany(
            "INSERT INTO source_postings VALUES(?,?,?)",
            [("alpha", "same", "u1"), ("beta", "same", "u2")])
        conn.executemany(
            "INSERT INTO opportunity_course_scores VALUES(?,?,?)",
            [("u1", "electrical_engineering", 80),
             ("u2", "computer_science", 65)])
        conn.executemany(
            "INSERT INTO discovery_state VALUES(?,?)",
            [("alpha", "same"), ("beta", "same")])
    return filename


def test_only_exact_source_identity_is_transferred(tmp_path):
    path = _fixture_db(tmp_path)
    with _sqlite_connect(path) as conn:
        result = _collect_inserts(conn, [("alpha", "same")])
    assert [x["id"] for x in result["opportunities"]] == ["u1"]
    assert [(x["source"], x["source_job_id"]) for x in result["source_postings"]] == [
        ("alpha", "same")]
    assert [x["course_id"] for x in result["opportunity_course_scores"]] == [
        "electrical_engineering"]
    assert [(x["source"], x["source_job_id"]) for x in result["discovery_state"]] == [
        ("alpha", "same")]


def test_snapshot_missing_opportunity_fails_closed(tmp_path):
    path = _fixture_db(tmp_path)
    with sqlite3.connect(path) as con:
        con.execute("DELETE FROM opportunities WHERE id='u1'")
    with _sqlite_connect(path) as con:
        with pytest.raises(RuntimeError, match="Missing opportunities"):
            _collect_inserts(con, [("alpha", "same")])


def test_apply_requires_matching_source_and_target_guards():
    with pytest.raises(RuntimeError, match="snapshot hash"):
        _run_additive(None, None, {"postgres_fingerprint": "g",
                                 "candidate_insert_count": 1},
                      expected_source_sha256="a", snapshot_sha256="b",
                      expected_postgres_fingerprint="g", expected_inserts=1)
    with pytest.raises(RuntimeError, match="fingerprint"):
        _run_additive(None, None, {"postgres_fingerprint": "bad",
                                 "candidate_insert_count": 1},
                      expected_source_sha256="a", snapshot_sha256="a",
                      expected_postgres_fingerprint="good", expected_inserts=1)
    with pytest.raises(RuntimeError, match="Candidate count"):
        _run_additive(None, None, {"postgres_fingerprint": "g",
                                 "candidate_insert_count": 2},
                      expected_source_sha256="a", snapshot_sha256="a",
                      expected_postgres_fingerprint="g", expected_inserts=1)


def test_sqlite_source_is_query_only(tmp_path):
    path = _fixture_db(tmp_path)
    with _sqlite_connect(path) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO opportunities(id) VALUES('u3')")
    assert len(_sha256(path)) == 64


def test_backup_utilities_required_even_with_valid_dsn(monkeypatch, tmp_path):
    from tools.stage_postgres_additions import _backup_with_pg_dump
    monkeypatch.setattr("shutil.which", lambda executable: None)
    with pytest.raises(RuntimeError, match="pg_dump"):
        _backup_with_pg_dump("postgresql://example:example@localhost/db", tmp_path)
