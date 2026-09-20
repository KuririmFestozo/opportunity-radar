from collectors import corporate_ats

HOME_HTML = """
<html><body>
  <a href="/go/Nossas-Oportunidades/8723700/">Nossas Oportunidades</a>
  <a href="/go/Estagios/8723701/">Estágios</a>
  <a href="/job/Rio-de-Janeiro-Teste/1425264500/">vaga</a>
</body></html>
"""

LISTING_HTML = """
<html><body>
<li class="jobResultItem">
  <a href="/job/Rio-de-Janeiro-Estagio-de-Verao/1425264500/">Estágio de Verão</a>
  <div>Localização Rio de Janeiro País/Região BR</div>
</li>
</body></html>
"""

DETAIL_HTML = """
<html><body><main>
<h1>Estágio de Verão</h1>
<div>Location:</div><div>Rio de Janeiro</div>
<div class="jobdescription">Estágio de verão para estudantes de Engenharia Elétrica.</div>
</main></body></html>
"""


def test_registry_portal_validation_requires_stable_id():
    try:
        corporate_ats.validate_successfactors_portal({"name": "Empresa", "career_url": "https://example.com"})
    except ValueError as exc:
        assert "id estável" in str(exc)
    else:
        raise AssertionError("validation should fail")


def test_homepage_discovers_multiple_go_listing_pages():
    urls = corporate_ats.parse_successfactors_listing_links(HOME_HTML, "https://carrera.ternium.com/")
    assert urls == [
        "https://carrera.ternium.com/go/Nossas-Oportunidades/8723700/",
        "https://carrera.ternium.com/go/Estagios/8723701/",
    ]


def test_successfactors_ids_are_namespaced_between_companies():
    assert corporate_ats._namespaced_job_id("ternium", "1425264500") == "ternium:1425264500"
    assert corporate_ats._namespaced_job_id("other", "1425264500") != "ternium:1425264500"


def test_detail_keeps_native_id_in_metadata_and_namespaces_source_id():
    job = corporate_ats.parse_successfactors_detail(
        DETAIL_HTML,
        "https://carrera.ternium.com/job/Rio-de-Janeiro-Estagio-de-Verao/1425264500/",
        portal_id="ternium",
        company="Ternium",
    )
    assert job is not None
    assert job.source_job_id == "ternium:1425264500"
    assert job.metadata["native_job_id"] == "1425264500"
    assert job.metadata["portal_id"] == "ternium"


def test_registry_entry_can_collect_from_discovered_listing(monkeypatch):
    calls=[]
    def fake_get_text(url):
        calls.append(url)
        if url == "https://example.com/":
            return '<a href="/go/Jobs/123/">Jobs</a>'
        if "/job/" in url:
            return DETAIL_HTML
        return LISTING_HTML
    monkeypatch.setattr(corporate_ats, "get_text", fake_get_text)
    jobs = corporate_ats.collect_successfactors({
        "id": "example",
        "name": "Example Co",
        "career_url": "https://example.com/",
        "queries": [""],
        "page_size": 25,
        "max_pages_per_query": 1,
        "max_jobs": 10,
        "max_details": 1,
    })
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "example:1425264500"
    assert any("/go/Jobs/123/" in url for url in calls)
