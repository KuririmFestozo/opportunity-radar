from storage.postgres_repository import PostgresOpportunityRepository


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


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
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        return _FakeResult(self.row)

    def cursor(self):
        return _FakeCursor(self)


def _repo(row=None):
    repo = object.__new__(PostgresOpportunityRepository)
    repo.conn = _FakeConnection(row=row)
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
