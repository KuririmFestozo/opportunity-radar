from urllib.parse import parse_qs, urlsplit

from collectors import corporate_ats


def _payload(job_id: int, title: str):
    return {
        "totalJobs": 1,
        "jobSearchResult": [
            {
                "response": {
                    "id": job_id,
                    "unifiedStandardTitle": title,
                    "unifiedUrlTitle": title.replace(" ", "-"),
                    "jobLocationShort": ["São Paulo, BR"],
                    "supportedLocales": ["pt_BR"],
                }
            }
        ],
    }


def test_targeted_csb_uses_only_nonempty_keywords(monkeypatch):
    calls = []

    def fake_get(url):
        if "/job/" in url:
            raise AssertionError("detail should not be fetched")
        if "/search/" in url:
            return '<a href="/search/?locale=pt_BR">PT</a>'
        return "<html></html>"

    def fake_post(url, payload):
        calls.append(dict(payload))
        if payload["keywords"] == "intern":
            return _payload(101, "Engineering Intern")
        return {"totalJobs": 0, "jobSearchResult": []}

    monkeypatch.setattr(corporate_ats, "get_text", fake_get)
    monkeypatch.setattr(corporate_ats, "_post_successfactors_json", fake_post)

    result = corporate_ats.collect_successfactors_with_stats({
        "id": "example",
        "name": "Example",
        "career_url": "https://jobs.example.com/",
        "queries": ["", "intern", "trainee"],
        "targeted_early_career": True,
        "targeted_max_queries": 2,
        "targeted_max_pages_per_query": 1,
        "targeted_max_csb_locales": 1,
        "targeted_html_fallback": False,
        "targeted_broad_fallback_pages": 0,
        "try_csb_json": True,
        "try_tile_search": True,
        "max_details": 0,
    })

    assert result.stats["mode"] == "targeted_early_career"
    assert len(result.jobs) == 1
    assert result.jobs[0].source_job_id == "example:101"
    assert calls
    assert all(call["keywords"] for call in calls)
    assert {call["keywords"] for call in calls} == {"intern", "trainee"}


def test_targeted_html_fallback_never_walks_blank_catalog(monkeypatch):
    urls = []

    def fake_get(url):
        urls.append(url)
        if url == "https://jobs.example.com/":
            return "<html></html>"
        query = parse_qs(urlsplit(url).query).get("q", [""])[0]
        if query == "intern":
            return '<a href="/job/Engineering-Intern/202/">Engineering Intern</a>'
        return "<html></html>"

    monkeypatch.setattr(corporate_ats, "get_text", fake_get)

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
    })

    assert len(result.jobs) == 1
    assert result.jobs[0].source_job_id == "example:202"
    search_urls = [url for url in urls if "/search/" in url]
    assert search_urls
    assert all(
        parse_qs(urlsplit(url).query).get("q", [""])[0]
        for url in search_urls
    )


def test_targeted_broad_fallback_filters_non_early_career_titles(monkeypatch):
    def fake_get(url):
        if url == "https://jobs.example.com/":
            return "<html></html>"
        if "tile-search-results" in url:
            return (
                '<li class="job-tile job-id-301" data-url="/job/Senior-Manager/301/">'
                '<a class="jobTitle-link" href="/job/Senior-Manager/301/">Senior Manager</a></li>'
                '<li class="job-tile job-id-302" data-url="/job/Intern/302/">'
                '<a class="jobTitle-link" href="/job/Intern/302/">Software Intern</a></li>'
            )
        return "<html></html>"

    monkeypatch.setattr(corporate_ats, "get_text", fake_get)

    result = corporate_ats.collect_successfactors_with_stats({
        "id": "example",
        "name": "Example",
        "career_url": "https://jobs.example.com/",
        "queries": ["intern"],
        "targeted_early_career": True,
        "targeted_html_fallback": False,
        "targeted_broad_fallback_pages": 1,
        "try_csb_json": False,
        "try_tile_search": True,
        "max_details": 0,
    })

    assert [job.source_job_id for job in result.jobs] == ["example:302"]
    assert result.stats["tile_requests"] == 1
