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
    def __init__(self, row=None, rows=None, row_queue=None):
        self.row = row
        self.rows = rows or []
        self.row_queue = list(row_queue or [])
        self.calls = []
        self.committed = False

    def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        row = self.row_queue.pop(0) if self.row_queue else self.row
        return _FakeResult(row, self.rows)

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed = True


def _repo(row=None, rows=None, row_queue=None):
    repo = object.__new__(PostgresOpportunityRepository)
    repo.conn = _FakeConnection(
        row=row,
        rows=rows,
        row_queue=row_queue,
    )
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


def _posting_payload(**overrides):
    from models.job import Job

    values = {
        "source": "example",
        "source_job_id": "job-1",
        "company": "Example",
        "title": "Engineering Intern",
        "location": "São Carlos - SP",
        "url": "https://example.com/jobs/1",
        "description": "Work with engineering systems.",
        "detected_intents": ["internship"],
        "course_scores": {"electrical_engineering": 88},
        "metadata": {},
    }
    values.update(overrides)
    return Job(**values)


def _prepare_row(job, *, processing_version=None):
    from storage.job_store import PROCESSING_VERSION, raw_content_hash

    return {
        "normalized_job_json": job.to_dict(),
        "raw_hash": raw_content_hash(job),
        "processing_version": processing_version or PROCESSING_VERSION,
    }


def test_prepare_posting_marks_unknown_identity_as_new():
    incoming = _posting_payload()
    repo = _repo(row=None)

    job, status, needs_processing = repo.prepare_posting(incoming)

    assert job is incoming
    assert status == "new"
    assert needs_processing is True
    assert len(repo.conn.calls) == 1


def test_prepare_posting_returns_cached_job_when_raw_content_is_unchanged():
    cached = _posting_payload(
        detected_intents=["internship"],
        course_scores={"electrical_engineering": 91},
    )
    incoming = _posting_payload(
        detected_intents=[],
        course_scores={},
    )
    repo = _repo(row=_prepare_row(cached))

    job, status, needs_processing = repo.prepare_posting(incoming)

    assert status == "unchanged"
    assert needs_processing is False
    assert job.detected_intents == ["internship"]
    assert job.course_scores == {"electrical_engineering": 91}
    assert len(repo.conn.calls) == 1


def test_prepare_posting_reprocesses_same_raw_content_after_version_change():
    cached = _posting_payload()
    incoming = _posting_payload()
    repo = _repo(row=_prepare_row(cached, processing_version="old-version"))

    job, status, needs_processing = repo.prepare_posting(incoming)

    assert status == "reprocess"
    assert needs_processing is True
    assert job.source_job_id == "job-1"


def test_prepare_posting_marks_changed_raw_content_for_processing():
    cached = _posting_payload(description="Old description")
    incoming = _posting_payload(description="New description")
    repo = _repo(row=_prepare_row(cached))

    job, status, needs_processing = repo.prepare_posting(incoming)

    assert status == "changed"
    assert needs_processing is True
    assert job.description == "New description"


def test_prepare_posting_reuses_rich_cached_fields_from_lightweight_stub():
    cached = _posting_payload(
        description="Detailed description",
        location="São Carlos - SP",
        employment_type="Internship",
    )
    incoming = _posting_payload(
        description="",
        location="",
        employment_type=None,
    )
    repo = _repo(row=_prepare_row(cached))

    job, status, needs_processing = repo.prepare_posting(incoming)

    assert status == "unchanged"
    assert needs_processing is False
    assert job.description == "Detailed description"
    assert job.location == "São Carlos - SP"
    assert job.employment_type == "Internship"


def test_prepare_posting_persists_metadata_only_source_reference_refresh():
    cached = _posting_payload(
        metadata={
            "source_references": [
                {
                    "source": "example",
                    "source_job_id": "job-1",
                    "url": "https://example.com/jobs/1",
                }
            ]
        }
    )
    incoming = _posting_payload(
        metadata={
            "source_references": [
                {
                    "source": "example",
                    "source_job_id": "job-1",
                    "url": "https://example.com/jobs/1",
                },
                {
                    "source": "mirror",
                    "source_job_id": "mirror-1",
                    "url": "https://mirror.example/jobs/1",
                },
            ]
        }
    )
    repo = _repo(row=_prepare_row(cached))

    job, status, needs_processing = repo.prepare_posting(incoming)

    assert status == "unchanged"
    assert needs_processing is False
    assert len(job.metadata["source_references"]) == 2
    assert len(repo.conn.calls) == 2

    kind, sql, args = repo.conn.calls[1]
    assert kind == "execute"
    assert "SET normalized_job_json = %s" in sql
    assert args[1:] == ("example", "job-1")


def test_upsert_posting_core_creates_stable_identity_rows_for_new_posting():
    from storage.unified_schema import _stable_opportunity_id

    job = _posting_payload(
        latitude=-22.0174,
        longitude=-47.8860,
        location_confidence="city",
    )
    repo = _repo(row_queue=[None])

    opportunity_id = repo._upsert_posting_core(
        job,
        seen_at="2026-09-24T16:00:00+00:00",
    )

    expected_id = _stable_opportunity_id("example", "job-1")
    assert opportunity_id == expected_id
    assert len(repo.conn.calls) == 3

    _, select_sql, select_args = repo.conn.calls[0]
    assert "FROM public.source_postings" in select_sql
    assert select_args == ("example", "job-1")

    _, opportunity_sql, opportunity_args = repo.conn.calls[1]
    assert "INSERT INTO public.opportunities" in opportunity_sql
    assert "extensions.st_point" in opportunity_sql
    assert "%s::double precision" in opportunity_sql
    assert "ON CONFLICT(id) DO UPDATE" in opportunity_sql
    assert opportunity_args[0] == expected_id
    assert opportunity_args[5:9] == (
        -22.0174,
        -47.8860,
        -47.8860,
        -22.0174,
    )

    _, posting_sql, posting_args = repo.conn.calls[2]
    assert "INSERT INTO public.source_postings" in posting_sql
    assert "'identity'" in posting_sql
    assert posting_args[0:3] == ("example", "job-1", expected_id)
    assert posting_args[8] == "2026-09-24T16:00:00+00:00"
    assert posting_args[9] == "2026-09-24T16:00:00+00:00"
    assert posting_args[10] == "2026-09-24T16:00:00+00:00"
    assert posting_args[11] == "2026-09-24T16:00:00+00:00"
    assert posting_args[12] == "2026-09-24T16:00:00+00:00"


def test_upsert_posting_core_preserves_existing_association_and_first_seen():
    from storage.job_store import raw_content_hash

    job = _posting_payload(description="Same content")
    existing_id = "00000000-0000-0000-0000-000000000123"
    old_first_seen = "2026-09-01T10:00:00+00:00"
    old_last_changed = "2026-09-02T10:00:00+00:00"
    repo = _repo(
        row_queue=[
            {
                "opportunity_id": existing_id,
                "first_seen_at": old_first_seen,
                "last_changed_at": old_last_changed,
                "raw_hash": raw_content_hash(job),
            }
        ]
    )

    opportunity_id = repo._upsert_posting_core(
        job,
        seen_at="2026-09-24T16:00:00+00:00",
    )

    assert opportunity_id == existing_id

    _, opportunity_sql, opportunity_args = repo.conn.calls[1]
    assert opportunity_args[0] == existing_id
    assert opportunity_args[-2] == old_first_seen
    assert opportunity_args[-1] == old_last_changed

    _, posting_sql, posting_args = repo.conn.calls[2]
    conflict_update = posting_sql.split(
        "ON CONFLICT(source, source_job_id) DO UPDATE SET",
        1,
    )[1]
    assert "opportunity_id =" not in conflict_update
    assert "first_seen_at =" not in conflict_update
    assert "association_method =" not in conflict_update
    assert posting_args[2] == existing_id
    assert posting_args[8] == old_first_seen
    assert posting_args[11] == old_last_changed


def test_upsert_posting_core_advances_last_changed_when_raw_content_changes():
    job = _posting_payload(description="New description")
    repo = _repo(
        row_queue=[
            {
                "opportunity_id": "00000000-0000-0000-0000-000000000123",
                "first_seen_at": "2026-09-01T10:00:00+00:00",
                "last_changed_at": "2026-09-02T10:00:00+00:00",
                "raw_hash": "different-hash",
            }
        ]
    )

    repo._upsert_posting_core(
        job,
        seen_at="2026-09-24T16:00:00+00:00",
    )

    opportunity_args = repo.conn.calls[1][2]
    posting_args = repo.conn.calls[2][2]
    assert opportunity_args[-1] == "2026-09-24T16:00:00+00:00"
    assert posting_args[11] == "2026-09-24T16:00:00+00:00"


def test_normalized_payload_removes_store_lifecycle_metadata():
    from storage.postgres_repository import _normalized_payload

    job = _posting_payload(
        metadata={
            "store_first_seen_at": "old",
            "store_miss_count": 2,
            "gupy_city": "São Carlos",
        }
    )

    payload = _normalized_payload(job)

    assert "store_first_seen_at" not in payload["metadata"]
    assert "store_miss_count" not in payload["metadata"]
    assert payload["metadata"]["gupy_city"] == "São Carlos"


def test_sync_opportunity_classification_uses_max_scores_and_union_intents():
    opportunity_id = "00000000-0000-0000-0000-000000000123"
    repo = _repo(
        rows=[
            {
                "normalized_job_json": {
                    "course_scores": {
                        "electrical_engineering": 82,
                        "computer_engineering": 60,
                    },
                    "detected_intents": ["internship"],
                }
            },
            {
                "normalized_job_json": {
                    "course_scores": {
                        "electrical_engineering": 94,
                        "computer_engineering": 55,
                    },
                    "detected_intents": [
                        "internship",
                        "summer_internship",
                    ],
                }
            },
        ]
    )

    repo._sync_opportunity_classification(opportunity_id)

    assert len(repo.conn.calls) == 5

    _, select_sql, select_args = repo.conn.calls[0]
    assert "SELECT normalized_job_json" in select_sql
    assert select_args == (opportunity_id,)

    _, delete_scores_sql, delete_scores_args = repo.conn.calls[1]
    assert "DELETE FROM public.opportunity_course_scores" in delete_scores_sql
    assert delete_scores_args == (opportunity_id,)

    kind, score_sql, score_rows = repo.conn.calls[2]
    assert kind == "executemany"
    assert "INSERT INTO public.opportunity_course_scores" in score_sql
    assert score_rows == [
        (opportunity_id, "computer_engineering", 60),
        (opportunity_id, "electrical_engineering", 94),
    ]

    _, delete_intents_sql, delete_intents_args = repo.conn.calls[3]
    assert "DELETE FROM public.opportunity_intents" in delete_intents_sql
    assert delete_intents_args == (opportunity_id,)

    kind, intent_sql, intent_rows = repo.conn.calls[4]
    assert kind == "executemany"
    assert "INSERT INTO public.opportunity_intents" in intent_sql
    assert intent_rows == [
        (opportunity_id, "internship"),
        (opportunity_id, "summer_internship"),
    ]


def test_sync_opportunity_classification_clears_stale_rows_when_empty():
    opportunity_id = "00000000-0000-0000-0000-000000000123"
    repo = _repo(
        rows=[
            {
                "normalized_job_json": {
                    "course_scores": {},
                    "detected_intents": [],
                }
            }
        ]
    )

    repo._sync_opportunity_classification(opportunity_id)

    assert len(repo.conn.calls) == 3
    assert "SELECT normalized_job_json" in repo.conn.calls[0][1]
    assert "DELETE FROM public.opportunity_course_scores" in repo.conn.calls[1][1]
    assert "DELETE FROM public.opportunity_intents" in repo.conn.calls[2][1]


def test_upsert_posting_runs_core_then_classification_without_implicit_commit():
    job = _posting_payload(
        course_scores={"electrical_engineering": 90},
        detected_intents=["internship"],
    )
    repo = _repo(
        row_queue=[None],
        rows=[
            {
                "normalized_job_json": job.to_dict(),
            }
        ],
    )

    repo.upsert_posting(
        job,
        seen_at="2026-09-24T17:00:00+00:00",
    )

    sql_calls = [call[1] for call in repo.conn.calls]
    assert any("INSERT INTO public.opportunities" in sql for sql in sql_calls)
    assert any("INSERT INTO public.source_postings" in sql for sql in sql_calls)
    assert any(
        "DELETE FROM public.opportunity_course_scores" in sql
        for sql in sql_calls
    )
    assert any(
        call[0] == "executemany"
        and "INSERT INTO public.opportunity_course_scores" in call[1]
        for call in repo.conn.calls
    )
    assert any(
        call[0] == "executemany"
        and "INSERT INTO public.opportunity_intents" in call[1]
        for call in repo.conn.calls
    )
    assert repo.conn.committed is False


def test_upsert_posting_can_commit_explicitly():
    job = _posting_payload()
    repo = _repo(
        row_queue=[None],
        rows=[
            {
                "normalized_job_json": job.to_dict(),
            }
        ],
    )

    repo.upsert_posting(
        job,
        seen_at="2026-09-24T17:00:00+00:00",
        commit=True,
    )

    assert repo.conn.committed is True
