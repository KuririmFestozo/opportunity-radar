from urllib.parse import parse_qs, urlsplit

from collectors import corporate_ats
from models.job import Job
from processing.classification import classify_job


LISTING_HTML = """
<html><body>
  <ul class="jobs-list">
    <li class="jobResultItem">
      <a href="/job/Rio-de-Janeiro-Est%C3%A1gio-de-Ver%C3%A3o-Ternium-2027/1425264500/">Estágio de Verão Ternium 2027</a>
      <div>Req No. 10184</div><div>Localização Rio de Janeiro</div><div>País/Região BR</div>
    </li>
    <li class="jobResultItem">
      <a href="/job/Rio-de-Janeiro-Mec%C3%A2nico-Industrial/1425000000/">Mecânico(a) Industrial</a>
      <div>Localização Rio de Janeiro</div><div>País/Região BR</div>
    </li>
  </ul>
</body></html>
"""

DETAIL_HTML = """
<html><body>
  <main>
    <h1>Estágio de Verão Ternium 2027</h1>
    <div>Data:</div><div>1 de set. de 2026</div>
    <div>Localização:</div><div>Rio de Janeiro</div>
    <div>Empresa:</div><div>Ternium</div>
    <div class="jobdescription">
      Programa de Estágio de Verão da Ternium Brasil.
      Requisitos: estar matriculado em Engenharia de Computação, Engenharia de Produção,
      Engenharia Elétrica, Engenharia Mecânica ou demais Engenharias.
    </div>
  </main>
</body></html>
"""


def test_successfactors_listing_finds_ternium_summer_job():
    refs = corporate_ats.parse_successfactors_listing(
        LISTING_HTML,
        "https://carrera.ternium.com/go/Nossas-Oportunidades/8723700/",
    )
    assert len(refs) == 2
    summer = next(ref for ref in refs if ref.native_job_id == "1425264500")
    assert summer.title == "Estágio de Verão Ternium 2027"
    assert summer.location == "Rio de Janeiro"
    assert summer.url == "https://carrera.ternium.com/job/Rio-de-Janeiro-Est%C3%A1gio-de-Ver%C3%A3o-Ternium-2027/1425264500/"


def test_successfactors_detail_preserves_course_requirements_and_date():
    job = corporate_ats.parse_successfactors_detail(
        DETAIL_HTML,
        "https://carrera.ternium.com/job/Rio-de-Janeiro-Est%C3%A1gio-de-Ver%C3%A3o-Ternium-2027/1425264500/",
        portal_id="ternium",
        company="Ternium",
    )
    assert job is not None
    assert job.source == "successfactors"
    assert job.source_job_id == "ternium:1425264500"
    assert job.company == "Ternium"
    assert job.location == "Rio de Janeiro"
    assert job.published_at.startswith("2026-09-01")
    assert "Engenharia Elétrica" in job.description

    classify_job(job)
    assert "summer_internship" in job.detected_intents
    assert "internship" in job.detected_intents
    assert job.course_scores["electrical_engineering"] >= 85
    assert job.course_scores["mechanical_engineering"] >= 85


def test_successfactors_listing_url_uses_query_and_startrow():
    url = corporate_ats._successfactors_listing_url(
        "https://carrera.ternium.com/go/Nossas-Oportunidades/8723700/",
        query="estágio de verão",
        startrow=25,
    )
    query = parse_qs(urlsplit(url).query)
    assert query["q"] == ["estágio de verão"]
    assert query["startrow"] == ["25"]
    assert query["sortColumn"] == ["referencedate"]


def test_successfactors_collector_fetches_priority_detail_only(monkeypatch):
    calls = []

    def fake_get_text(url):
        calls.append(url)
        if "/job/" in url:
            return DETAIL_HTML
        return LISTING_HTML

    monkeypatch.setattr(corporate_ats, "get_text", fake_get_text)
    jobs = corporate_ats.collect_successfactors({
        "id": "ternium",
        "name": "Ternium",
        "ats": "successfactors",
        "listing_url": "https://carrera.ternium.com/go/Nossas-Oportunidades/8723700/",
        "queries": [""],
        "max_pages_per_query": 1,
        "page_size": 25,
        "max_jobs": 20,
        "max_details": 1,
    })
    assert len(jobs) == 2
    summer = next(job for job in jobs if job.metadata.get("native_job_id") == "1425264500")
    mechanic = next(job for job in jobs if job.metadata.get("native_job_id") == "1425000000")
    assert summer.metadata["detail_fetched"] is True
    assert mechanic.metadata["detail_fetched"] is False
    assert len([url for url in calls if "/job/" in url]) == 1
