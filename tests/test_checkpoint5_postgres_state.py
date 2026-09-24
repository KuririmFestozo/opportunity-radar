from storage.postgres_repository import PostgresOpportunityRepository


class _FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def executemany(self, sql, rows):
        self.connection.calls.append(("executemany", sql, list(rows)))


class _FakeConnection:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
        self.calls = []
        self.committed = False

    def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        return _FakeResult(self.row, self.rows)

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed = True


def _repo(row=None, rows=None):
    repo = object.__new__(PostgresOpportunityRepository)
    repo.conn = _FakeConnection(row=row, rows=rows)
    return repo


def test_record_discoveries_deduplicates_and_keeps_catalog_precedence():
    repo = _repo()

    count = repo.record_discoveries(
        "example",
        ["job-2", "job-1", "job-1"],
        scope_status="out_of_scope",
        seen_at="2026-09-24T12:00:00+00:00",
    )

    assert count == 2
    kind, sql, rows = repo.conn.calls[0]
    assert kind == "executemany"
    assert "ON CONFLICT(source, source_job_id)" in sql
    assert "ds.scope_status = 'catalog'" in sql
    assert "excluded.scope_status = 'catalog'" in sql
    assert [row[1] for row in rows] == ["job-1", "job-2"]
    assert all(row[2] == "out_of_scope" for row in rows)


def test_record_discoveries_with_no_ids_is_noop():
    repo = _repo()

    assert repo.record_discoveries("example", []) == 0
    assert repo.conn.calls == []


def test_needs_full_audit_matches_existing_cadence():
    repo = _repo({"successful_runs": 6, "last_full_run": 0})

    assert repo.needs_full_audit("example", "global", every_runs=7) is True

    repo.conn.row = {"successful_runs": 5, "last_full_run": 0}
    assert repo.needs_full_audit("example", "global", every_runs=7) is False

    repo.conn.row = {"successful_runs": 12, "last_full_run": 6}
    assert repo.needs_full_audit("example", "global", every_runs=7) is True


def test_needs_full_audit_without_scope_state_is_false():
    repo = _repo(None)

    assert repo.needs_full_audit("example", "global") is False


def test_finish_scope_run_uses_atomic_upsert_for_complete_run():
    repo = _repo()

    repo.finish_scope_run(
        "example",
        "global",
        coverage="complete",
        finished_at="2026-09-24T12:00:00+00:00",
    )

    kind, sql, args = repo.conn.calls[0]
    assert kind == "execute"
    assert "ON CONFLICT(source, scope_key) DO UPDATE" in sql
    assert "scopes.successful_runs + 1" in sql
    assert "excluded.last_coverage = 'complete'" in sql
    assert args == (
        "example",
        "global",
        "complete",
        "complete",
        "2026-09-24T12:00:00+00:00",
    )


def test_mark_seen_ids_reopens_and_resets_lifecycle_state():
    repo = _repo({"n": 1})

    result = repo.mark_seen_ids(
        "example",
        ["job-2", "job-1", "job-1"],
        seen_at="2026-09-24T13:00:00+00:00",
    )

    assert result == {"seen": 2, "reopened": 1}
    assert repo.conn.calls[0][0] == "executemany"
    assert "discovery_state" in repo.conn.calls[0][1]

    _, select_sql, select_args = repo.conn.calls[1]
    assert "NOT is_active OR miss_count > 0" in select_sql
    assert select_args == ("example", ["job-1", "job-2"])

    _, update_sql, update_args = repo.conn.calls[2]
    assert "miss_count = 0" in update_sql
    assert "missing_since = NULL" in update_sql
    assert "inactive_at = NULL" in update_sql
    assert "is_active = true" in update_sql
    assert update_args == (
        "2026-09-24T13:00:00+00:00",
        "2026-09-24T13:00:00+00:00",
        "example",
        ["job-1", "job-2"],
    )


def test_mark_seen_postings_groups_by_source():
    from models.job import Job

    repo = _repo({"n": 0})
    jobs = [
        Job(
            source="alpha",
            source_job_id="1",
            company="A",
            title="One",
            location="",
            url="https://example.com/1",
        ),
        Job(
            source="alpha",
            source_job_id="2",
            company="A",
            title="Two",
            location="",
            url="https://example.com/2",
        ),
        Job(
            source="beta",
            source_job_id="3",
            company="B",
            title="Three",
            location="",
            url="https://example.com/3",
        ),
    ]

    result = repo.mark_seen_postings(
        jobs,
        seen_at="2026-09-24T13:00:00+00:00",
    )

    assert result == {"seen": 3, "reopened": 0}
    discovery_calls = [
        call for call in repo.conn.calls
        if call[0] == "executemany" and "discovery_state" in call[1]
    ]
    assert len(discovery_calls) == 2


def test_reconcile_scope_skips_partial_coverage_without_writes():
    repo = _repo()

    result = repo.reconcile_scope(
        "example",
        ["job-1"],
        coverage="partial",
        checked_at="2026-09-24T14:00:00+00:00",
    )

    assert result == {
        "coverage": "partial",
        "checked": 0,
        "seen": 1,
        "new_missing": 0,
        "inactivated": 0,
        "skipped": True,
    }
    assert repo.conn.calls == []


def test_reconcile_scope_matches_conservative_lifecycle_rules():
    repo = _repo(
        rows=[
            {
                "source_job_id": "seen",
                "is_active": True,
                "miss_count": 0,
                "missing_since": None,
            },
            {
                "source_job_id": "first-miss",
                "is_active": True,
                "miss_count": 0,
                "missing_since": None,
            },
            {
                "source_job_id": "second-miss",
                "is_active": True,
                "miss_count": 1,
                "missing_since": "2026-09-23T14:00:00+00:00",
            },
            {
                "source_job_id": "already-inactive",
                "is_active": False,
                "miss_count": 2,
                "missing_since": "2026-09-22T14:00:00+00:00",
            },
        ]
    )

    result = repo.reconcile_scope(
        "example",
        ["seen"],
        coverage="complete",
        miss_threshold=2,
        checked_at="2026-09-24T14:00:00+00:00",
    )

    assert result == {
        "coverage": "complete",
        "checked": 4,
        "seen": 1,
        "new_missing": 1,
        "inactivated": 1,
        "skipped": False,
    }

    _, select_sql, select_args = repo.conn.calls[0]
    assert "FROM public.source_postings" in select_sql
    assert select_args == ["example"]

    _, checked_sql, checked_args = repo.conn.calls[1]
    assert "SET last_checked_at = %s" in checked_sql
    assert checked_args == ["2026-09-24T14:00:00+00:00", "example"]

    kind, lifecycle_sql, lifecycle_rows = repo.conn.calls[2]
    assert kind == "executemany"
    assert "missing_since = COALESCE" in lifecycle_sql
    assert "is_active = CASE" in lifecycle_sql
    assert len(lifecycle_rows) == 2

    first_miss, second_miss = lifecycle_rows
    assert first_miss[0] == 1
    assert first_miss[2] is False
    assert first_miss[-1] == "first-miss"

    assert second_miss[0] == 2
    assert second_miss[2] is True
    assert second_miss[4] is True
    assert second_miss[-1] == "second-miss"


def test_reconcile_scope_applies_prefix_to_read_and_check_update():
    repo = _repo(rows=[])

    result = repo.reconcile_scope(
        "example",
        [],
        prefix="region:",
        coverage="complete",
        checked_at="2026-09-24T14:00:00+00:00",
    )

    assert result["checked"] == 0
    assert "source_job_id LIKE %s" in repo.conn.calls[0][1]
    assert repo.conn.calls[0][2] == ["example", "region:%"]
    assert "source_job_id LIKE %s" in repo.conn.calls[1][1]
    assert repo.conn.calls[1][2] == [
        "2026-09-24T14:00:00+00:00",
        "example",
        "region:%",
    ]


def test_touch_posting_refreshes_last_seen_and_reactivates():
    repo = _repo()

    repo.touch_posting(
        "example",
        "job-1",
        seen_at="2026-09-24T15:00:00+00:00",
    )

    kind, sql, args = repo.conn.calls[0]
    assert kind == "execute"
    assert "UPDATE public.source_postings" in sql
    assert "last_seen_at = %s" in sql
    assert "is_active = true" in sql
    assert args == (
        "2026-09-24T15:00:00+00:00",
        "example",
        "job-1",
    )
    assert repo.conn.committed is False


def test_touch_posting_can_commit_explicitly():
    repo = _repo()

    repo.touch_posting(
        "example",
        "job-1",
        seen_at="2026-09-24T15:00:00+00:00",
        commit=True,
    )

    assert repo.conn.committed is True
