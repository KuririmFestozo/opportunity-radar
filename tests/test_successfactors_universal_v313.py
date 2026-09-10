from collectors import corporate_ats


DANFOSS_HTML = """
<html><body>
<li class="jobResultItem">
  <a href="/job/Est%C3%A1gio-em-Engenharia/50202-en_GB/">Estágio em Engenharia</a>
  <div>Job Location: Osasco, BR</div>
</li>
</body></html>
"""


def test_v313_accepts_successfactors_locale_suffix_ids():
    refs = corporate_ats.parse_successfactors_listing(
        DANFOSS_HTML,
        "https://jobs.danfoss.com/search/",
    )
    assert len(refs) == 1
    assert refs[0].native_job_id == "50202"
    assert refs[0].title == "Estágio em Engenharia"


def test_v313_deduplicates_same_requisition_across_discovery_routes(monkeypatch):
    home = """
    <a href="/go/Engineering/123/">Engineering</a>
    <a href="/job/Test/111-en_GB/">Test Job</a>
    """
    listing = '<a href="/job/Test/111-en_GB/">Test Job</a>'

    def fake_get_text(url):
        if url == "https://example.com/":
            return home
        return listing

    monkeypatch.setattr(corporate_ats, "get_text", fake_get_text)
    result = corporate_ats.collect_successfactors_with_stats({
        "id": "example",
        "name": "Example",
        "career_url": "https://example.com/",
        "max_pages_per_listing": 1,
        "max_listing_urls": 5,
        "max_jobs": 20,
        "max_details": 0,
        "try_xml_feed": False,
        "keyword_fallback": False,
    })

    assert len(result.jobs) == 1
    assert result.jobs[0].source_job_id == "example:111"
    assert result.stats["unique_refs"] == 1
    assert result.stats["references_seen"] > result.stats["unique_refs"]


def test_v313_xml_feed_parser():
    xml = """
    <jobs><job>
      <jobReqId>9001</jobReqId>
      <title>Electrical Intern</title>
      <url>https://career5.successfactors.eu/job/X/9001/</url>
      <location>Boston, US</location>
    </job></jobs>
    """
    refs = corporate_ats.parse_successfactors_xml(
        xml,
        "https://career5.successfactors.eu/career",
    )
    assert len(refs) == 1
    assert refs[0].native_job_id == "9001"
    assert refs[0].location == "Boston, US"


def test_v313_constructs_xml_feed_when_company_id_is_known():
    urls = corporate_ats.discover_successfactors_xml_urls(
        "",
        "https://career5.successfactors.eu/career?company=ALSTOM",
    )
    assert len(urls) == 1
    assert "company=ALSTOM" in urls[0]
    assert "career_ns=job_listing_summary" in urls[0]
    assert "resultType=XML" in urls[0]


def test_v313_listing_discovery_includes_viewalljobs():
    html = '<a href="/viewalljobs/">All jobs</a><a href="/search/">Search</a>'
    urls = corporate_ats.parse_successfactors_listing_links(html, "https://jobs.example.com/")
    assert "https://jobs.example.com/viewalljobs/" in urls
    assert "https://jobs.example.com/search/" in urls
