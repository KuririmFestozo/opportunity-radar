from tools.plan_postgres_snapshot_refresh import plan_refresh


def row(source, job_id, *, raw="a", version="3.14", active=True,
        changed="2026-09-20T00:00:00+00:00", seen="2026-09-20T00:00:00+00:00",
        miss_count=0):
    return {
        "source": source, "source_job_id": job_id,
        "raw_hash": raw, "processing_version": version,
        "is_active": active, "last_changed_at": changed,
        "last_seen_at": seen, "miss_count": miss_count,
    }


def test_plan_refresh_keeps_both_sides_and_counts_lifecycle_diffs():
    sqlite_rows = [
        row("a", "same", raw="new", active=False,
            changed="2026-10-08T00:00:00+00:00",
            seen="2026-10-08T00:00:00+00:00", miss_count=2),
        row("a", "new-only"),
    ]
    postgres_rows = [
        row("a", "same", raw="old", active=True),
        row("b", "remote-only"),
    ]
    plan = plan_refresh(sqlite_rows, postgres_rows)
    assert plan["shared_postings"] == 1
    assert plan["sqlite_only"] == 1
    assert plan["postgres_only"] == 1
    assert plan["union_postings_if_preserved"] == 3
    assert plan["metrics"]["shared_raw_hash_diff"] == 1
    assert plan["metrics"]["shared_sqlite_content_newer"] == 1
    assert plan["metrics"]["shared_sqlite_seen_newer"] == 1
    assert plan["metrics"]["shared_active_status_diff"] == 1
    assert plan["metrics"]["sqlite_inactive_postgres_active"] == 1
    assert plan["metrics"]["shared_miss_count_diff"] == 1
    assert plan["metrics"]["only_postgres_active"] == 1
    assert plan["per_source"]["a"]["only_sqlite"] == 1
    assert plan["per_source"]["b"]["only_postgres"] == 1


def test_plan_refresh_no_change_is_reported_cleanly():
    example = row("a", "same")
    result = plan_refresh([example], [example])
    assert result["shared_postings"] == 1
    assert result["metrics"]["shared_content_same_timestamp"] == 1
    assert result["metrics"]["shared_seen_same_timestamp"] == 1
    assert "shared_raw_hash_diff" not in result["metrics"]


def test_plan_refresh_rejects_duplicate_identifiers():
    try:
        plan_refresh([row("a", "1"), row("a", "1")], [])
        assert False, "duplicate should have raised"
    except ValueError as exc:
        assert "Identidade duplicada" in str(exc)
