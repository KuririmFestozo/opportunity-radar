import json
from collections import Counter

import pytest

from collectors import eightfold, inhire, smartrecruiters, teamtailor, workday
from config import additional_ats
from config.eightfold import EIGHTFOLD_TENANTS
from main import _run, additional_ats_runtime
from tools.check_regional_coverage import coverage, load_rows


@pytest.mark.parametrize("module", [workday, smartrecruiters])
def test_scope_and_limit_count_complete_page_before_truncating(monkeypatch, capsys, module):
    def response(*a, **k):
        if module is workday:
            return {"total": 100, "jobPostings": [{"title": title, "externalPath": f"/job/R{i}"} for i, title in enumerate(["Senior Manager", "Engineering Intern", "Engineering Intern", "Engineering Intern"])]}
        return {"totalFound": 100, "content": [{"id": str(i), "name": title} for i, title in enumerate(["Senior Manager", "Engineering Intern", "Engineering Intern", "Engineering Intern"])]}
    monkeypatch.setattr(module, "post_json" if module is workday else "get_json", response)
    cfg = {"id": "x", "name": "X", "board_url": "https://x.wd1.myworkdayjobs.com/en-US/Careers", "company_identifier": "X",
           "queries": ["intern", "trainee"], "max_jobs": 2, "early_career_only": True, "show_incremental_stats": True}
    jobs = getattr(module, "collect_workday" if module is workday else "collect_smartrecruiters")(cfg)
    assert len(jobs) == 2
    assert jobs[0].title == "Senior Manager"
    assert jobs[1].title == "Engineering Intern"
    log = capsys.readouterr().out
    assert "4 refs brutas | 4 únicas | 3 early-career" in log
    assert "2 elegíveis observadas fora do teto" in log and "até 96 refs" in log
    assert "1 consultas não executadas" in log


def test_limit_is_reported_without_verbose_stats(monkeypatch, capsys):
    monkeypatch.setattr(smartrecruiters, "get_json", lambda *a, **k: {"totalFound": 100, "content": [{"id": "1", "name": "Intern"}, {"id": "2", "name": "Intern"}]})
    smartrecruiters.collect_smartrecruiters({"id": "x", "name": "X", "company_identifier": "X", "max_jobs": 1})
    assert "[LIMIT]" in capsys.readouterr().out


@pytest.mark.parametrize("new", [False, True])
def test_inhire_fast_stop_only_for_wholly_known_catalog(monkeypatch, capsys, new):
    monkeypatch.setattr(inhire, "get_json", lambda *a, **k: {"jobsPage": [{"id": "2" if new else "1", "title": "Intern"}]})
    inhire.collect_inhire({"id": "x", "name": "X", "tenant": "x", "known_source_job_ids": {"x:1"}, "show_incremental_stats": True})
    assert ("[FAST-STOP]" in capsys.readouterr().out) is not new


def test_teamtailor_skips_known_details_but_full_refresh_revalidates(monkeypatch):
    calls = []
    def get(url):
        calls.append(url)
        if url.endswith("/jobs"):
            return '<a href="/jobs/1-intern"><span title="Engineering Intern">Intern</span></a>'
        return '<script type="application/ld+json">{"@type":"JobPosting","title":"Engineering Intern","description":"Updated"}</script>'
    monkeypatch.setattr(teamtailor, "get_text", get)
    class Store:
        def known_ids(self, *a, **k):
            return {"x:1"}
    cfg = {"id": "x", "name": "X", "career_url": "https://example.com"}
    teamtailor.collect_teamtailor(additional_ats_runtime(cfg, "teamtailor", Store(), False))
    assert len(calls) == 1
    calls.clear()
    jobs = teamtailor.collect_teamtailor(additional_ats_runtime(cfg, "teamtailor", Store(), True))
    assert len(calls) == 2 and jobs[0].description == "Updated"


def eight_cfg():
    return {"id": "a", "name": "A", "career_url": "https://careers.example.com", "domain": "example.com"}


def test_eightfold_public_pagination_and_known_details(monkeypatch):
    calls = []
    def get(url, params):
        calls.append((url, params))
        if "position_details" in url:
            return {"data": {"jobDescription": "<p>Public description</p>"}}
        i = params["start"] + 1
        return {"data": {"count": 2, "positions": [{"id": i, "name": "Intern", "locations": ["São Carlos"],
                    "postedTs": 1000, "workLocationOption": "hybrid", "atsJobId": "native", "positionUrl": f"/careers/job/{i}"}]}}
    monkeypatch.setattr(eightfold, "get_json", get)
    jobs = eightfold.collect_eightfold(eight_cfg() | {"known_source_job_ids": {"a:1"}, "skip_known_details": True})
    assert len(jobs) == 2 and len(calls) == 3
    assert jobs[1].description == "Public description" and jobs[0].workplace_type == "hybrid"
    assert jobs[0].location == "São Carlos" and jobs[0].source_job_id == "a:1"
    assert jobs[0].url == "https://careers.example.com/careers/job/1"
    assert jobs[0].published_at.startswith("1970-")
    assert [p["start"] for u, p in calls if u.endswith("/search")] == [0, 1]


@pytest.mark.parametrize("empty", [False, True])
def test_eightfold_stops_empty_or_repeated(monkeypatch, empty):
    calls = []
    def get(*a, **k):
        calls.append(1)
        return {"data": {"count": 100, "positions": [] if empty else [{"id": 1, "name": "Intern"}]}}
    monkeypatch.setattr(eightfold, "get_json", get)
    jobs = eightfold.collect_eightfold(eight_cfg() | {"max_details": 0})
    assert len(calls) == (1 if empty else 2) and len(jobs) == (0 if empty else 1)


def test_eightfold_detail_and_tenant_failures_are_isolated(monkeypatch):
    def get(url, params):
        if params["domain"] == "bad.example" or "position_details" in url:
            raise TimeoutError()
        return {"data": {"count": 1, "positions": [{"id": 1, "name": "Intern"}]}}
    monkeypatch.setattr(eightfold, "get_json", get)
    jobs, counts = [], Counter()
    _run("bad", lambda: eightfold.collect_eightfold(eight_cfg() | {"domain": "bad.example"}), jobs, counts)
    _run("good", lambda: eightfold.collect_eightfold(eight_cfg()), jobs, counts)
    assert len(jobs) == 1 and jobs[0].description == ""


def test_registry_has_no_duplicate_tenants_or_boards():
    for registry, key in [(additional_ats.WORKDAY_BOARDS, "board_url"), (additional_ats.SMARTRECRUITERS_BOARDS, "company_identifier"),
                          (additional_ats.INHIRE_TENANTS, "tenant"), (additional_ats.IZIRH_TENANTS, "subdomain"),
                          (additional_ats.TOTVS_TENANTS, "tenant"), (additional_ats.TEAMTAILOR_BOARDS, "career_url"),
                          (EIGHTFOLD_TENANTS, "domain")]:
        assert len(registry) == len({r["id"] for r in registry}) == len({r[key].casefold() for r in registry})


def test_local_regional_diagnostic_deduplicates_and_handles_accents(tmp_path):
    rows = [{"source": "a", "source_job_id": "1", "company": "A", "location": "Sao Carlos, SP"},
            {"source": "a", "source_job_id": "2", "company": "B", "location": "Gavião Peixoto, SP"},
            {"source": "a", "source_job_id": "3", "company": "A", "location": "São Carlos do Ivaí, PR"}]
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(rows[:2] + rows[:1]), encoding="utf-8")
    result = coverage(load_rows(None, path))
    assert result["São Carlos"] == {"A": 1}
    assert result["Gavião Peixoto"] == {"B": 1}
    assert coverage(rows[:2], "gaviao peixoto")["gaviao peixoto"] == {"B": 1}


def test_local_diagnostic_missing_db_does_not_create_file(tmp_path):
    import sqlite3
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        list(load_rows(path))
    assert not path.exists()
