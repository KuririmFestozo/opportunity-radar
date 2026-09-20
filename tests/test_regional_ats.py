import json

import pytest

from check_regional_sources import regional_matches
from collectors import gupy_global, teamtailor, totvs
from collectors.structured_posting import posting_data
from config.successfactors import SUCCESSFACTORS_PORTALS
from storage.job_store import JobStore


def totvs_row(native="uuid-1", title="Estágio", city="São Carlos"):
    return f'''<div data-id="{native}" data-code="121" data-title="{title}"
        data-page-url="/x/job-opportunity/121" data-city-name="{city}"
        data-state-small-name="SP" data-remote-string="Remoto">
        <a href="https://atracaodetalentos.totvs.app/x/121/estagio">{title}</a></div>'''


def detail(title="Estágio"):
    return '<script type="application/ld+json">' + json.dumps({
        "@type": "JobPosting", "title": title, "description": r"Ol\u00e1 &lt;b&gt;mundo&lt;/b&gt;",
        "datePosted": "2026-09-18", "validThrough": "2026-10-18", "employmentType": "CONTRACTOR",
        "jobLocation": {"address": {"addressLocality": "São Carlos", "addressRegion": "SP", "addressCountry": "BR"}},
    }) + ';</script>'


def test_totvs_preserves_id_full_description_regime_and_actual_workplace(monkeypatch):
    page = detail() + '''<p data-cy="desktop-regime">CLT</p>
        <p data-cy="desktop-subtitle">X | São Carlos - SP | Presencial</p>
        <div data-cy="desktop-description">Descrição</div>
        <div data-cy="desktop-responsibilities">Responsabilidades</div>
        <div data-cy="desktop-requirements">Requisitos</div>'''
    monkeypatch.setattr(totvs, "get_text", lambda url: totvs_row() if url.endswith("/x") else page)
    jobs = totvs.collect_totvs({"id": "x", "name": "X", "tenant": "x"})
    job = jobs[0]
    assert job.source_job_id == "x:uuid-1" and job.metadata["code"] == "121"
    assert job.url.endswith("/x/121/estagio") and job.location == "São Carlos, SP"
    assert job.employment_type == "CLT" and job.workplace_type == "on-site"
    assert job.description == "Descrição\n\nResponsabilidades\n\nRequisitos"
    assert job.metadata["valid_through"] == "2026-10-18"


def test_totvs_known_catalog_one_request_keeps_cached_details(monkeypatch, tmp_path):
    cfg = {"id": "x", "name": "X", "tenant": "x"}
    calls = []
    def get(url):
        calls.append(url)
        return totvs_row() if url.endswith("/x") else detail()
    monkeypatch.setattr(totvs, "get_text", get)
    job = totvs.collect_totvs(cfg)[0]
    assert job.description == "Olá mundo"
    assert job.workplace_type is None  # UI translation is not the job's modality.
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job, commit=True)
        calls.clear()
        incoming = totvs.collect_totvs(cfg | {"known_source_job_ids": {job.source_job_id}, "skip_known_details": True})[0]
        assert len(calls) == 1
        assert store.prepare(incoming)[1:] == ("unchanged", False)
        assert store.prepare(incoming)[0].description == "Olá mundo"


def test_totvs_known_ids_do_not_hide_new_or_duplicate_jobs(monkeypatch):
    monkeypatch.setattr(totvs, "get_text", lambda url: totvs_row() + totvs_row() + totvs_row("uuid-2"))
    jobs = totvs.collect_totvs({"id": "x", "name": "X", "tenant": "x", "max_details": 0,
                               "known_source_job_ids": {"x:uuid-1"}})
    assert {j.source_job_id for j in jobs} == {"x:uuid-1", "x:uuid-2"}


def test_totvs_detail_failure_preserves_listing_and_missing_fields(monkeypatch):
    def get(url):
        if url.endswith("/x"):
            return totvs_row(city="")
        raise TimeoutError()
    monkeypatch.setattr(totvs, "get_text", get)
    job = totvs.collect_totvs({"id": "x", "name": "X", "tenant": "x"})[0]
    assert job.description == "" and job.employment_type is None
    assert job.published_at is None


def tt_page(ids, next_page=None):
    html = "".join(f'<a href="/pt-BR/jobs/{i}-estagio"><span title="Estágio">Est...</span><span>Brazil</span></a>' for i in ids)
    return html + (f'<a href="/jobs/show_more?page={next_page}">More</a>' if next_page else "")


def test_teamtailor_follows_public_pagination_keeps_full_title_and_new_ids(monkeypatch):
    calls = []
    pages = {"https://careers.example.com/jobs": tt_page([1], 2),
             "https://careers.example.com/jobs/show_more?page=2": tt_page([1, 2])}
    def get(url):
        calls.append(url)
        return pages[url]
    monkeypatch.setattr(teamtailor, "get_text", get)
    jobs = teamtailor.collect_teamtailor({"id": "t", "name": "T", "career_url": "https://careers.example.com",
                                        "max_details": 0, "known_source_job_ids": {"t:1"}})
    assert len(calls) == 2
    assert {j.source_job_id for j in jobs} == {"t:1", "t:2"}
    assert all(j.title == "Estágio" for j in jobs)


def test_teamtailor_stops_repeated_pages_and_ignores_external_links(monkeypatch):
    calls = []
    def get(url):
        calls.append(url)
        return tt_page([1], len(calls) + 1) + '<a href="https://elsewhere.example/jobs/999-job">External</a>'
    monkeypatch.setattr(teamtailor, "get_text", get)
    jobs = teamtailor.collect_teamtailor({"id": "t", "name": "T", "career_url": "https://careers.example.com", "max_details": 0})
    assert len(calls) == 2 and len(jobs) == 1


def test_teamtailor_maps_detail_and_continues_when_detail_fails(monkeypatch):
    def get(url):
        if url.endswith("/jobs"):
            return tt_page([1, 2])
        if "/1-" in url:
            return detail("Estágio em Dados")
        raise TimeoutError()
    monkeypatch.setattr(teamtailor, "get_text", get)
    jobs = teamtailor.collect_teamtailor({"id": "t", "name": "T", "career_url": "https://careers.example.com"})
    assert len(jobs) == 2 and jobs[0].title == "Estágio em Dados"
    assert jobs[0].location == "São Carlos, SP, BR" and jobs[1].description == ""


def test_structured_data_skips_malformed_script_and_reads_graph():
    assert posting_data('<script type="application/ld+json">bad</script>' + detail())["title"] == "Estágio"
    assert posting_data('<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"T"}]}</script>')["title"] == "T"


@pytest.mark.parametrize("company,native", [("Vagas Faber-Castell Brasil", 12278134), ("TATU MARCHESAN", 11304276)])
def test_regional_companies_use_existing_gupy_global_mapping(monkeypatch, company, native):
    item = {"id": native, "name": "Estágio", "careerPageName": company,
            "jobUrl": f"https://example.gupy.io/jobs/{native}", "city": "São Carlos"}
    monkeypatch.setattr(gupy_global, "get_json", lambda *a, **k: {"data": [item], "pagination": {"total": 1}})
    monkeypatch.setattr(gupy_global.time, "sleep", lambda *a: None)
    jobs = gupy_global.collect_gupy_global({"native_job_types": ["vacancy_type_internship"],
        "keyword_queries": ["intern"], "max_pages_per_native_type": 1, "max_pages_per_keyword": 1})
    assert len(jobs) == 1 and jobs[0].source == "gupy_global"
    assert any(regional_matches([jobs[0].to_dict()]).values())


def test_regional_successfactors_reuses_existing_collector():
    ids = [p["id"] for p in SUCCESSFACTORS_PORTALS]
    assert len(ids) == len(set(ids))
    for name in ("citrosuco", "volkswagen"):
        portal = next(p for p in SUCCESSFACTORS_PORTALS if p["id"] == name)
        assert portal["ats"] == "successfactors" and portal["enabled"]
