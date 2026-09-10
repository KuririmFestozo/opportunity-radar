from collectors import corporate_ats


TILE_HTML = '''
<ul>
  <li class="job-tile job-id-50202" data-url="/job/Estagio-em-Engenharia/50202-en_GB/">
    <a class="jobTitle-link" href="/job/Estagio-em-Engenharia/50202-en_GB/">Estágio em Engenharia</a>
    <div id="job-50202-section-city-value">Osasco, BR</div>
  </li>
</ul>
'''

CSB_PAYLOAD = {
    "totalJobs": 1,
    "jobSearchResult": [
        {
            "response": {
                "id": 50202,
                "unifiedStandardTitle": "Estágio em Engenharia",
                "unifiedUrlTitle": "Est%C3%A1gio-em-Engenharia",
                "jobLocationShort": ["Osasco, BR<br/>"] ,
                "unifiedStandardStart": "9/1/26",
                "supportedLocales": ["en_GB"],
            }
        }
    ],
}


def test_v3131_parses_rmk_tile_fragment():
    refs = corporate_ats.parse_successfactors_tiles(
        TILE_HTML,
        "https://jobs.danfoss.com/tile-search-results/?startrow=0",
    )
    assert len(refs) == 1
    assert refs[0].native_job_id == "50202"
    assert refs[0].location == "Osasco, BR"


def test_v3131_parses_csb_unified_json():
    refs, total = corporate_ats.parse_successfactors_csb_json(
        CSB_PAYLOAD,
        "https://jobs.danfoss.com",
        "en_GB",
    )
    assert total == 1
    assert len(refs) == 1
    assert refs[0].native_job_id == "50202"
    assert refs[0].title == "Estágio em Engenharia"
    assert refs[0].location == "Osasco, BR"
    assert refs[0].url.endswith("/50202-en_GB/")
    assert refs[0].published_at.startswith("2026-09-01")


def test_v3131_locale_discovery_prioritizes_config_and_falls_back_to_en_gb():
    html = '<a href="/search/?q=&locale=pt_BR">PT</a><a href="/search/?locale=de_DE">DE</a>'
    locales = corporate_ats.discover_successfactors_locales(html, {"csb_locales": ["en_US"]})
    assert locales[0] == "en_US"
    assert "pt_BR" in locales
    assert "de_DE" in locales
    assert "en_GB" in locales


def test_v3131_universal_collector_uses_csb_json_when_html_shell_is_empty(monkeypatch):
    def fake_get_text(url):
        if "/job/" in url:
            raise AssertionError("detail should not be fetched")
        if "/search/" in url:
            return '<html><a href="/search/?locale=en_GB">English</a></html>'
        return "<!DOCTYPE html><html></html>"

    def fake_post(url, payload):
        assert url == "https://jobs.danfoss.com/services/recruiting/v1/jobs"
        if payload["locale"] == "en_GB" and payload["pageNumber"] == 0:
            return CSB_PAYLOAD
        return {"totalJobs": 0, "jobSearchResult": []}

    monkeypatch.setattr(corporate_ats, "get_text", fake_get_text)
    monkeypatch.setattr(corporate_ats, "_post_successfactors_json", fake_post)

    result = corporate_ats.collect_successfactors_with_stats({
        "id": "danfoss",
        "name": "Danfoss",
        "career_url": "https://jobs.danfoss.com/",
        "try_tile_search": True,
        "try_csb_json": True,
        "try_xml_feed": False,
        "keyword_fallback": False,
        "csb_locales": ["en_GB"],
        "max_csb_locales": 1,
        "max_csb_pages_per_locale": 1,
        "max_tile_pages": 1,
        "max_pages_per_listing": 1,
        "max_listing_urls": 3,
        "max_details": 0,
        "max_jobs": 100,
    })

    assert len(result.jobs) == 1
    assert result.jobs[0].source_job_id == "danfoss:50202"
    assert result.stats["method_counts"]["csb_json"] == 1
    assert result.stats["csb_json_requests"] == 1


def test_v3131_deduplicates_tile_and_csb_json_by_native_req_id(monkeypatch):
    def fake_get_text(url):
        if "tile-search-results" in url:
            return TILE_HTML
        if "/search/" in url:
            return '<html><a href="/search/?locale=en_GB">English</a></html>'
        return "<html></html>"

    monkeypatch.setattr(corporate_ats, "get_text", fake_get_text)
    monkeypatch.setattr(corporate_ats, "_post_successfactors_json", lambda *_: CSB_PAYLOAD)

    result = corporate_ats.collect_successfactors_with_stats({
        "id": "danfoss",
        "name": "Danfoss",
        "career_url": "https://jobs.danfoss.com/",
        "try_tile_search": True,
        "try_csb_json": True,
        "try_xml_feed": False,
        "keyword_fallback": False,
        "csb_locales": ["en_GB"],
        "max_csb_locales": 1,
        "max_csb_pages_per_locale": 1,
        "max_tile_pages": 1,
        "max_pages_per_listing": 1,
        "max_listing_urls": 3,
        "max_details": 0,
        "max_jobs": 100,
    })

    assert len(result.jobs) == 1
    assert result.stats["references_seen"] >= 2
    assert result.stats["unique_refs"] == 1
    methods = result.jobs[0].metadata["discovery_methods"]
    assert "tile" in methods
    assert "csb_json" in methods
