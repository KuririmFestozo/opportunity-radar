from models.job import Job
from storage.job_store import JobStore
from storage.incremental_state import (
    ensure_incremental_schema,
    finish_scope_run,
    known_discovery_ids,
    lifecycle_stats,
    mark_seen_jobs,
    needs_full_audit,
    reconcile_scope,
    record_discoveries,
)
from config.additional_ats import INHIRE_TENANTS, IZIRH_TENANTS


def make_job(source_job_id="tenant:1"):
    return Job(
        source="inhire",
        source_job_id=source_job_id,
        company="Example",
        title="Engineering Intern",
        location="São Paulo, SP",
        url="https://example.test/job/1",
    )


def test_out_of_scope_discovery_is_remembered_without_catalog_job(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        record_discoveries(
            store,
            "successfactors",
            {"ey:100", "ey:101"},
            scope_status="out_of_scope",
        )
        store.commit()

        assert known_discovery_ids(
            store,
            "successfactors",
            prefix="ey:",
        ) == {"ey:100", "ey:101"}
        assert store.count() == 0
        assert lifecycle_stats(store)["out_of_scope_discoveries"] == 2


def test_partial_scan_never_counts_as_missing(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        store.upsert(make_job(), commit=False)
        mark_seen_jobs(store, [make_job()])
        store.commit()

        result = reconcile_scope(
            store,
            "inhire",
            set(),
            prefix="tenant:",
            coverage="partial",
        )
        store.commit()

        assert result["skipped"] is True
        job = store.load_jobs(active_only=False)[0]
        assert job.metadata["store_lifecycle_state"] == "active"
        assert job.metadata["store_miss_count"] == 0


def test_two_complete_misses_inactivate_and_reappearance_reopens(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        store.upsert(make_job(), commit=False)
        mark_seen_jobs(store, [make_job()])
        store.commit()

        first = reconcile_scope(
            store,
            "inhire",
            set(),
            prefix="tenant:",
            coverage="complete",
            miss_threshold=2,
        )
        store.commit()
        assert first["new_missing"] == 1
        assert first["inactivated"] == 0
        assert (
            store.load_jobs(active_only=False)[0]
            .metadata["store_lifecycle_state"]
            == "missing"
        )

        second = reconcile_scope(
            store,
            "inhire",
            set(),
            prefix="tenant:",
            coverage="complete",
            miss_threshold=2,
        )
        store.commit()
        assert second["inactivated"] == 1
        assert store.load_jobs(active_only=True) == []
        assert (
            store.load_jobs(active_only=False)[0]
            .metadata["store_lifecycle_state"]
            == "inactive"
        )

        mark_seen_jobs(store, [make_job()])
        store.commit()
        reopened = store.load_jobs(active_only=True)[0]
        assert reopened.metadata["store_lifecycle_state"] == "active"
        assert reopened.metadata["store_miss_count"] == 0


def test_periodic_full_audit_after_partial_runs(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        scope = "tenant:"
        finish_scope_run(store, "izirh", scope, coverage="complete")
        for _ in range(5):
            finish_scope_run(store, "izirh", scope, coverage="partial")
        assert needs_full_audit(
            store, "izirh", scope, every_runs=7
        ) is False

        finish_scope_run(store, "izirh", scope, coverage="partial")
        assert needs_full_audit(
            store, "izirh", scope, every_runs=7
        ) is True


def test_checkpoint3_source_expansion_is_unique_and_enabled():
    inhire_ids = [row["id"] for row in INHIRE_TENANTS]
    izi_ids = [row["id"] for row in IZIRH_TENANTS]
    assert len(inhire_ids) == len(set(inhire_ids))
    assert len(izi_ids) == len(set(izi_ids))

    assert {
        "v360", "bridge", "cielo", "db1", "gx2",
        "jassy", "dati", "isystems", "yandeh", "iconit",
    } <= {row["id"] for row in INHIRE_TENANTS if row["enabled"]}

    assert {"levva", "advice", "sertec"} <= {
        row["id"] for row in IZIRH_TENANTS if row["enabled"]
    }

def test_daily_audit_keeps_known_ids_but_disables_early_stop(tmp_path):
    from main import additional_ats_runtime

    with JobStore(tmp_path / "radar.db") as store:
        ensure_incremental_schema(store)
        job = Job(
            source="izirh",
            source_job_id="tenant:1",
            company="Example",
            title="Intern",
            location="",
            url="https://example.test/1",
        )
        store.upsert(job, commit=False)
        mark_seen_jobs(store, [job])
        store.commit()

        runtime = additional_ats_runtime(
            {"id": "tenant", "name": "Example"},
            "izirh",
            store,
            False,
            False,
            True,
        )

        assert runtime["known_source_job_ids"] == {"tenant:1"}
        assert runtime["early_stop_known_pages"] == 0
        assert runtime["skip_known_details"] is True

def test_aldak_is_disabled_until_public_tenant_is_valid_again():
    aldak = next(
        row for row in INHIRE_TENANTS
        if row["id"] == "aldaktecnologia"
    )
    assert aldak["enabled"] is False
