import json

from models.job import Job
from storage.job_store import JobStore, deduplicate_source_jobs


def make_job(source="successfactors", source_job_id="danfoss:50202", **kwargs):
    base = dict(
        source=source,
        source_job_id=source_job_id,
        company="Danfoss",
        title="Engineering Intern",
        location="Osasco, BR",
        url="https://jobs.danfoss.com/job/x/50202-en_GB/",
        description="Full description",
        detected_intents=["internship"],
        course_scores={"electrical_engineering": 88},
        metadata={"ats": "successfactors"},
    )
    base.update(kwargs)
    return Job(**base)


def test_store_persists_and_reuses_cached_job(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        store.upsert(make_job(), commit=True)
        stub = make_job(
            description="",
            detected_intents=[],
            course_scores={},
        )
        prepared, status, needs_processing = store.prepare(stub)

        assert status == "unchanged"
        assert needs_processing is False
        assert prepared.description == "Full description"
        assert prepared.course_scores["electrical_engineering"] == 88


def test_changed_job_requires_processing(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        store.upsert(make_job(), commit=True)
        changed = make_job(title="Electrical Engineering Intern")
        prepared, status, needs_processing = store.prepare(changed)

        assert status == "changed"
        assert needs_processing is True
        assert prepared.title == "Electrical Engineering Intern"


def test_known_ids_can_be_scoped_to_successfactors_tenant(tmp_path):
    with JobStore(tmp_path / "radar.db") as store:
        store.upsert(make_job(), commit=False)
        store.upsert(
            make_job(source_job_id="metso:123", company="Metso"),
            commit=False,
        )
        store.upsert(
            make_job(source="gupy", source_job_id="999"),
            commit=False,
        )
        store.commit()

        assert store.known_ids(
            "successfactors",
            prefix="danfoss:",
        ) == {"danfoss:50202"}


def test_bootstrap_existing_jobs_json_only_once(tmp_path):
    exported = tmp_path / "jobs.json"
    exported.write_text(
        json.dumps([make_job().to_dict()], ensure_ascii=False),
        encoding="utf-8",
    )

    with JobStore(tmp_path / "radar.db") as store:
        assert store.bootstrap_from_json(exported)["imported"] == 1
        assert store.count() == 1
        assert store.bootstrap_from_json(exported)["imported"] == 0


def test_source_dedup_keeps_different_sources():
    sf_stub = make_job(description="")
    sf_full = make_job()
    gupy = make_job(source="gupy", source_job_id="123")

    result = deduplicate_source_jobs([sf_stub, sf_full, gupy])

    assert len(result) == 2
    sf = next(job for job in result if job.source == "successfactors")
    assert sf.description == "Full description"
