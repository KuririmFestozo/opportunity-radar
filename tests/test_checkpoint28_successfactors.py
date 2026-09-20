import pytest

from collectors import successfactors_incremental as probe
from config.successfactors import SUCCESSFACTORS_PORTALS


def setup_pages(monkeypatch, method, pages):
    calls = []
    def response(*args):
        page = pages[min(len(calls), len(pages) - 1)]
        calls.append(args)
        if method == "tile":
            return "".join(f'<li class="job-tile job-id-{ident}" data-url="/job/x/{ident}/"><a class="jobTitle-link">{title}</a></li>' for ident, title in page)
        return {"jobSearchResult": [{"response": {"id": ident, "unifiedStandardTitle": title}} for ident, title in page], "totalJobs": 100}
    monkeypatch.setattr(probe, "get_text" if method == "tile" else "_post_successfactors_json", response)
    return calls


def config(method):
    return {"id": "x", "career_url": "https://example.com", "try_tile_search": method == "tile",
            "try_csb_json": method == "csb", "csb_locales": ["en_US"], "targeted_early_career": True}


@pytest.mark.parametrize("method", ["tile", "csb"])
def test_two_pages_with_new_senior_and_known_intern_do_not_trigger_targeted(monkeypatch, method):
    calls = setup_pages(monkeypatch, method, [[("1", "Engineering Intern"), ("2", "Senior Manager")], [("3", "Senior Engineer")]])
    result = probe.probe_successfactors_recent(config(method), {"x:1"})
    assert result.safe_stop and len(calls) == 2
    assert result.new_native_ids == result.catalog_new_native_ids == {"2", "3"}
    assert result.relevant_new_native_ids == set()
    assert "2 novos catálogo | 0 novos early-career" in result.summary("X")


@pytest.mark.parametrize("method", ["tile", "csb"])
@pytest.mark.parametrize("title,uncertain", [("Engineering Intern", False), ("", True), ("Job", True), ("123", True)])
def test_relevant_or_insufficient_title_prevents_stop(monkeypatch, method, title, uncertain):
    calls = setup_pages(monkeypatch, method, [[("1", "Senior Engineer")], [("2", title)]])
    result = probe.probe_successfactors_recent(config(method), {"x:9"})
    assert not result.safe_stop and len(calls) == 2
    assert result.catalog_new_native_ids == {"1", "2"}
    assert (result.uncertain_new_native_ids if uncertain else result.relevant_new_native_ids) == {"2"}


@pytest.mark.parametrize("method", ["tile", "csb"])
def test_repeated_page_is_inconclusive_not_second_clean_page(monkeypatch, method):
    calls = setup_pages(monkeypatch, method, [[("1", "Senior Manager")]])
    result = probe.probe_successfactors_recent(config(method), {"x:9"})
    assert not result.safe_stop and len(calls) == 2
    assert "repetida" in result.reason


@pytest.mark.parametrize("method", ["tile", "csb"])
def test_universal_override_still_detects_any_new_id(monkeypatch, method):
    setup_pages(monkeypatch, method, [[("1", "Senior Manager")]])
    result = probe.probe_successfactors_recent(config(method) | {"targeted_early_career": False}, {"x:9"})
    assert not result.safe_stop and result.new_native_ids == {"1"}


def test_corrected_boot_portals_and_disabled_legacy_reason():
    portals = {p["id"]: p for p in SUCCESSFACTORS_PORTALS}
    for ident, host in [("delaval", "delaval-careers.jobs.hr.cloud.sap"), ("basf", "basf.jobs"), ("tetra_pak", "jobs.tetrapak.com")]:
        assert portals[ident]["enabled"]
        assert host in portals[ident]["career_url"]
        assert portals[ident]["try_csb_json"]
    assert not portals["amkor"]["enabled"] and "Legacy" in portals["amkor"]["disabled_reason"]
