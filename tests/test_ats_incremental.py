from collections import Counter

import pytest

from collectors import inhire, izirh, smartrecruiters, workday
from config import additional_ats as registry
from main import _run, additional_ats_runtime
from models.job import Job
from storage.job_store import JobStore


@pytest.mark.parametrize("name,required", [
    ("INHIRE_TENANTS", {"elogroup", "magazineluiza", "willbank", "nomadglobal", "kiwify", "semantix", "alice", "involves"}),
    ("IZIRH_TENANTS", {"embraer", "programasembraer", "ems", "cellerafarma"}),
    ("WORKDAY_BOARDS", {"hitachi", "mastercard", "roche", "santander", "db", "edenpeople", "erm", "hbfuller", "medtronic"}),
    ("SMARTRECRUITERS_BOARDS", {"bosch", "aumovio", "experian", "continental", "louisdreyfuscompany", "jitterbit", "rotork1", "veoliaenvironnementsa", "syntegon", "applusidiada1"}),
    ("TOTVS_TENANTS", {"xmobots"}), ("TEAMTAILOR_BOARDS", {"tecumseh"}),
])
def test_registries_unique_and_expanded(name, required):
    rows = getattr(registry, name)
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert required <= {row["id"] for row in rows if row["enabled"]}


def izi_config():
    return {"id": "a", "name": "A", "subdomain": "a.izirh.io", "page_size": 10,
            "known_source_job_ids": {f"a:{i}" for i in range(100)}, "show_incremental_stats": True}


@pytest.mark.parametrize("new_on_page,expected_calls", [(None, 2), (1, 4)])
def test_izirh_known_streak_resets(monkeypatch, capsys, new_on_page, expected_calls):
    calls = []
    monkeypatch.setattr(izirh, "get_json", lambda *a: {"tenantId": "a"})
    def post(url, payload):
        assert payload["payload"]["orderBy"] == {"name": "createdAt", "order": "desc"}
        page = len(calls)
        calls.append(payload)
        rows = [{"id": str(i), "name": "Estágio"} for i in range(page * 10, page * 10 + 10)]
        if page == new_on_page:
            rows[0]["id"] = "new"
        return {"data": {"data": rows, "vacanciesNumber": 100}}
    monkeypatch.setattr(izirh, "post_json", post)
    jobs = izirh.collect_izirh(izi_config())
    assert len(calls) == expected_calls
    assert len(jobs) == expected_calls * 10
    assert "[FAST-STOP]" in capsys.readouterr().out


def test_izirh_repeated_page_stops_even_full_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(izirh, "get_json", lambda *a: {"tenantId": "a"})
    def post(*args):
        calls.append(1)
        return {"data": {"data": [{"id": str(i), "name": "Job"} for i in range(10)], "vacanciesNumber": 100}}
    monkeypatch.setattr(izirh, "post_json", post)
    cfg = izi_config() | {"known_source_job_ids": set()}
    assert len(izirh.collect_izirh(cfg)) == 10
    assert len(calls) == 2


def test_inhire_one_request_all_known_still_checks_content(monkeypatch, capsys, tmp_path):
    calls = []
    def get(*a, **k):
        calls.append(1)
        return {"jobsPage": [{"id": "1", "title": "Intern", "description": "Original"}]}
    monkeypatch.setattr(inhire, "get_json", get)
    cfg = {"id": "a", "name": "A", "tenant": "a", "known_source_job_ids": {"a:1"}, "show_incremental_stats": True}
    jobs = inhire.collect_inhire(cfg)
    assert len(calls) == 1 and len(jobs) == 1
    assert "1 conhecidos | 0 novos | 1" in capsys.readouterr().out
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.upsert(jobs[0], commit=True)
    assert store.prepare(jobs[0])[1:] == ("unchanged", False)
    changed = Job(**(jobs[0].to_dict() | {"description": "Updated"}))
    assert store.prepare(changed)[1:] == ("changed", True)
    store.close()


@pytest.mark.parametrize("ats", ["workday", "smartrecruiters"])
def test_queries_deduplicate_before_cap_and_do_not_stop_on_known(monkeypatch, ats):
    module = workday if ats == "workday" else smartrecruiters
    calls = []
    def response(query, offset):
        calls.append((query, offset))
        start = 0 if query == "intern" else 10
        ids = range(start + offset, start + offset + 10)
        if ats == "workday":
            return {"total": 30, "jobPostings": [{"title": "Intern", "externalPath": f"/job/R{i}", "bulletFields": [f"R{i}"]} for i in ids]}
        return {"totalFound": 30, "content": [{"id": str(i), "name": "Intern"} for i in ids]}
    if ats == "workday":
        monkeypatch.setattr(module, "post_json", lambda url, payload, **kw: response(payload["searchText"], payload["offset"]))
        cfg = {"board_url": "https://a.wd1.myworkdayjobs.com/en-US/Careers"}
        known = {f"a:R{i}" for i in range(30)}
    else:
        monkeypatch.setattr(module, "get_json", lambda url, params, **kw: response(params["q"], params["offset"]))
        cfg = {"company_identifier": "A"}
        known = {f"a:{i}" for i in range(30)}
    cfg.update(id="a", name="A", queries=["intern", "trainee"], page_size=10,
               max_pages_per_query=3, max_jobs=40, known_source_job_ids=known, early_stop_known_pages=2)
    jobs = getattr(module, f"collect_{ats}")(cfg)
    assert len(jobs) == 40
    assert len(calls) == 6
    assert ("trainee", 20) in calls


@pytest.mark.parametrize("ats", ["workday", "smartrecruiters"])
@pytest.mark.parametrize("empty", [False, True])
def test_query_pages_stop_on_empty_or_repeated(monkeypatch, ats, empty):
    calls = []
    def response(*a, **kw):
        calls.append(1)
        if ats == "workday":
            return {"total": 100, "jobPostings": [] if empty else [{"title": "Intern", "externalPath": f"/job/R{i}"} for i in range(10)]}
        return {"totalFound": 100, "content": [] if empty else [{"id": str(i), "name": "Intern"} for i in range(10)]}
    module = workday if ats == "workday" else smartrecruiters
    monkeypatch.setattr(module, "post_json" if ats == "workday" else "get_json", response)
    cfg = {"id": "a", "name": "A", "company_identifier": "A", "board_url": "https://a.wd1.myworkdayjobs.com/en-US/Careers", "page_size": 10, "max_pages_per_query": 10}
    getattr(module, f"collect_{ats}")(cfg)
    assert len(calls) == (1 if empty else 2)


def test_runtime_scopes_ids_and_full_refresh():
    class Store:
        def known_ids(self, source, *, prefix):
            assert (source, prefix) == ("totvs", "xmobots:")
            return {"xmobots:1"}
    source = {"id": "xmobots", "name": "Xmobots"}
    assert additional_ats_runtime(source, "totvs", Store(), False)["known_source_job_ids"] == {"xmobots:1"}
    full = additional_ats_runtime(source, "totvs", Store(), True)
    assert not full["known_source_job_ids"] and not full["skip_known_details"]
    assert full["early_stop_known_pages"] == 0
    assert "known_source_job_ids" not in source


def test_company_failure_does_not_stop_next_source():
    jobs, stats = [], Counter()
    def fail():
        raise RuntimeError("offline")
    job = Job("totvs", "x:1", "X", "Intern", "", "https://example.com")
    _run("failed", fail, jobs, stats)
    _run("next", lambda: [job], jobs, stats)
    assert jobs == [job] and stats["totvs"] == 1
