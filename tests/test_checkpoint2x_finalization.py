from urllib.parse import parse_qs, urlsplit

from collectors import corporate_ats
from collectors.ats_stats import SearchStats
from config.additional_ats import SMARTRECRUITERS_BOARDS, WORKDAY_BOARDS
from models.job import Job


def test_explicit_query_hit_is_preserved_even_when_title_is_not_early_career():
    stats = SearchStats(
        {"name": "Example", "early_career_only": True, "max_jobs": 0},
        ["intern"],
    )
    job = Job(
        source="smartrecruiters",
        source_job_id="example:1",
        company="Example",
        title="Senior Manager",
        location="",
        url="https://example.test/1",
    )
    assert stats.admit(job, query_scoped=True)
    assert "example:1" in stats.query_scoped
    assert "example:1" in stats.eligible


def test_query_scoped_ats_registries_do_not_have_product_caps():
    assert SMARTRECRUITERS_BOARDS
    assert WORKDAY_BOARDS
    assert all(board.get("max_jobs") == 0 for board in SMARTRECRUITERS_BOARDS)
    assert all(board.get("max_pages_per_query") == 0 for board in SMARTRECRUITERS_BOARDS)
    assert all(board.get("max_jobs") == 0 for board in WORKDAY_BOARDS)
    assert all(board.get("max_pages_per_query") == 0 for board in WORKDAY_BOARDS)


def _html_page(ids):
    return "".join(
        f'<a href="/job/Engineering-Intern/{job_id}/">Engineering Intern</a>'
        for job_id in ids
    )


def test_successfactors_targeted_stops_query_after_known_recent_pages(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        if url == "https://jobs.example.com/":
            return "<html></html>"
        if "/search/" not in url:
            return "<html></html>"
        qs = parse_qs(urlsplit(url).query)
        startrow = int(qs.get("startrow", ["0"])[0])
        if startrow == 0:
            return _html_page(range(1, 11))
        if startrow == 10:
            return _html_page(range(11, 21))
        return _html_page(range(21, 31))

    monkeypatch.setattr(corporate_ats, "get_text", fake_get)

    result = corporate_ats.collect_successfactors_with_stats({
        "id": "example",
        "name": "Example",
        "career_url": "https://jobs.example.com/",
        "queries": ["intern"],
        "targeted_early_career": True,
        "targeted_max_queries": 1,
        "page_size": 10,
        "targeted_max_pages_per_query": 0,
        "targeted_max_jobs": 0,
        "targeted_query_early_stop": True,
        "targeted_query_early_stop_known_pages": 2,
        "targeted_broad_fallback_pages": 0,
        "try_csb_json": False,
        "try_tile_search": False,
        "max_details": 0,
        "known_source_job_ids": {
            f"example:{job_id}" for job_id in range(1, 21)
        },
    })

    search_calls = [url for url in calls if "/search/" in url]
    assert len(search_calls) == 2
    assert len(result.jobs) == 20
    assert result.stats["query_early_stop_hits"] == 1


def test_successfactors_targeted_can_disable_query_early_stop(monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        if url == "https://jobs.example.com/":
            return "<html></html>"
        if "/search/" not in url:
            return "<html></html>"
        qs = parse_qs(urlsplit(url).query)
        startrow = int(qs.get("startrow", ["0"])[0])
        if startrow == 0:
            return _html_page(range(1, 11))
        if startrow == 10:
            return _html_page(range(11, 21))
        return ""

    monkeypatch.setattr(corporate_ats, "get_text", fake_get)

    result = corporate_ats.collect_successfactors_with_stats({
        "id": "example",
        "name": "Example",
        "career_url": "https://jobs.example.com/",
        "queries": ["intern"],
        "targeted_early_career": True,
        "targeted_max_queries": 1,
        "page_size": 10,
        "targeted_max_pages_per_query": 0,
        "targeted_max_jobs": 0,
        "targeted_query_early_stop": False,
        "targeted_broad_fallback_pages": 0,
        "try_csb_json": False,
        "try_tile_search": False,
        "max_details": 0,
        "known_source_job_ids": {
            f"example:{job_id}" for job_id in range(1, 21)
        },
    })

    search_calls = [url for url in calls if "/search/" in url]
    assert len(search_calls) == 3
    assert len(result.jobs) == 20
    assert result.stats["query_early_stop_hits"] == 0


def test_successfactors_targeted_initializes_query_stop_without_known_ids(monkeypatch):
    monkeypatch.setattr(
        corporate_ats,
        "get_text",
        lambda url: "<html></html>",
    )
    result = corporate_ats.collect_successfactors_with_stats({
        "id": "example",
        "name": "Example",
        "career_url": "https://jobs.example.com/",
        "queries": ["intern"],
        "targeted_early_career": True,
        "targeted_max_queries": 1,
        "targeted_max_pages_per_query": 1,
        "targeted_broad_fallback_pages": 0,
        "try_csb_json": False,
        "try_tile_search": False,
        "max_details": 0,
        "known_source_job_ids": set(),
    })
    assert result.stats["query_early_stop_enabled"] is False
    assert result.stats["query_early_stop_hits"] == 0
