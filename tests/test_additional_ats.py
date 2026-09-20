from collectors import inhire, izirh, smartrecruiters, workday
from config.additional_ats import (
    INHIRE_TENANTS,
    IZIRH_TENANTS,
    SMARTRECRUITERS_BOARDS,
    WORKDAY_BOARDS,
)
from config.successfactors import SUCCESSFACTORS_PORTALS


def test_inhire_maps_public_tenant_jobs_and_skips_closed(monkeypatch):
    monkeypatch.setattr(
        inhire,
        "get_json",
        lambda *args, **kwargs: {
            "tenantName": "EloGroup",
            "jobsPage": [
                {
                    "jobId": "abc-1",
                    "displayName": "Estágio em Dados",
                    "workplaceType": "Remote",
                    "location": "Brasil",
                    "status": "OPEN",
                },
                {
                    "jobId": "abc-2",
                    "displayName": "Vaga encerrada",
                    "status": "CLOSED",
                },
            ],
        },
    )
    jobs = inhire.collect_inhire(
        {"id": "elogroup", "name": "EloGroup", "tenant": "elogroup"}
    )
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "elogroup:abc-1"
    assert jobs[0].workplace_type == "remote"
    assert jobs[0].url.startswith("https://elogroup.inhire.app/vagas/abc-1/")


def test_izirh_resolves_tenant_and_maps_job(monkeypatch):
    monkeypatch.setattr(izirh, "get_json", lambda *a, **k: {"tenantId": "tenant-123"})

    def fake_post(url, payload, **kwargs):
        return {
            "result": {
                "vacanciesNumber": 1,
                "data": [
                    {
                        "id": "v-1",
                        "name": "Programa de Estágio",
                        "city": "SP - São José dos Campos",
                        "workModel": {"name": "Híbrido"},
                        "typeContraction": {"name": "Estágio"},
                        "createdAt": "2026-09-18T12:00:00Z",
                    }
                ],
            }
        }

    monkeypatch.setattr(izirh, "post_json", fake_post)
    jobs = izirh.collect_izirh(
        {"id": "embraer", "name": "Embraer", "subdomain": "embraer.izirh.io"}
    )
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "embraer:v-1"
    assert jobs[0].workplace_type == "hybrid"
    assert "São José dos Campos" in jobs[0].location
    assert jobs[0].url.endswith("/visualizar-vaga/v-1")


def test_workday_uses_public_cxs(monkeypatch):
    calls = []

    def fake_post(url, payload, **kwargs):
        calls.append((url, payload))
        return {
            "total": 1,
            "jobPostings": [
                {
                    "title": "Engineering Intern",
                    "externalPath": "/job/Brazil/Engineering-Intern_R0135418",
                    "locationsText": "Guarulhos, São Paulo, Brazil",
                    "postedOn": "Posted Today",
                    "bulletFields": ["R0135418"],
                }
            ],
        }

    monkeypatch.setattr(workday, "post_json", fake_post)
    jobs = workday.collect_workday(
        {
            "id": "hitachi",
            "name": "Hitachi",
            "board_url": "https://hitachi.wd1.myworkdayjobs.com/en-US/hitachi",
            "queries": ["intern"],
            "max_pages_per_query": 1,
        }
    )
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "hitachi:R0135418"
    assert calls[0][0].endswith("/wday/cxs/hitachi/hitachi/jobs")
    assert calls[0][1]["searchText"] == "intern"


def test_smartrecruiters_uses_public_posting_api(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append((url, params))
        return {
            "totalFound": 1,
            "content": [
                {
                    "id": "744000144746919",
                    "uuid": "uuid-1",
                    "name": "Programa de Estágio Superior",
                    "location": {"city": "Campinas", "region": "SP", "country": "Brazil"},
                    "releasedDate": "2026-08-21T00:00:00Z",
                    "typeOfEmployment": {"label": "Internship"},
                }
            ],
        }

    monkeypatch.setattr(smartrecruiters, "get_json", fake_get)
    jobs = smartrecruiters.collect_smartrecruiters(
        {
            "id": "bosch",
            "name": "Bosch Group",
            "company_identifier": "BoschGroup",
            "queries": ["estágio"],
            "max_pages_per_query": 1,
        }
    )
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "bosch:744000144746919"
    assert "Campinas" in jobs[0].location
    assert calls[0][1]["q"] == "estágio"


def test_primary_new_sources_are_enabled():
    assert any(x["tenant"] == "elogroup" and x["enabled"] for x in INHIRE_TENANTS)
    assert any(
        x["subdomain"] == "embraer.izirh.io" and x["enabled"]
        for x in IZIRH_TENANTS
    )
    assert any(
        "hitachi.wd1.myworkdayjobs.com" in x["board_url"] and x["enabled"]
        for x in WORKDAY_BOARDS
    )
    identifiers = {x["company_identifier"] for x in SMARTRECRUITERS_BOARDS if x["enabled"]}
    assert {"BoschGroup", "Aumovio"} <= identifiers


def test_cpfl_registered_as_successfactors():
    cpfl = [x for x in SUCCESSFACTORS_PORTALS if x.get("id") == "cpfl"]
    assert len(cpfl) == 1
    assert cpfl[0]["enabled"] is True
    assert cpfl[0]["career_url"] == "https://vagas.cpfl.com.br/"
