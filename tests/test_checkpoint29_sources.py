from collectors import walljobs, cia_estagios, nube, iel, cia_talentos, superestagios
from config.early_career_sources import EARLY_CAREER_SOURCES


def test_registry_unique_and_documents_disabled_sources():
    ids = [row["id"] for row in EARLY_CAREER_SOURCES]
    assert len(ids) == len(set(ids))
    enabled = {row["id"] for row in EARLY_CAREER_SOURCES if row.get("enabled")}
    assert {"walljobs", "cia_estagios", "nube", "iel"} <= enabled
    for row in EARLY_CAREER_SOURCES:
        if not row.get("enabled"):
            assert row.get("disabled_reason")


def test_walljobs_public_cards(monkeypatch):
    html = '''<article><h3>Estágio de Engenharia</h3><span>Navegantes, SC, Brasil</span><span>R$ 1800,00</span><span>Expira em 30/11/2026</span><span>Estágio</span><a href="/vagas/acme-estagio-engenharia">Participar</a></article>'''
    monkeypatch.setattr(walljobs, "get_text", lambda *a, **k: html)
    jobs = walljobs.collect_walljobs({"max_jobs": 10, "show_incremental_stats": False})
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_job_id.endswith("acme-estagio-engenharia")
    assert job.title == "Estágio de Engenharia"
    assert job.location == "Navegantes, SC"
    assert job.salary == "R$ 1800,00"


def test_cia_estagios_skips_closed(monkeypatch):
    html = '''<div><h2>Programa de Estágio Danone 2027</h2><a href="/programa-danone">Fazer inscrição</a></div><div><h2>Programa de Estágio Clarios 2026</h2><a href="/programa-clarios">Inscrições encerradas</a></div>'''
    monkeypatch.setattr(cia_estagios, "get_text", lambda *a, **k: html)
    jobs = cia_estagios.collect_cia_estagios({"show_incremental_stats": False})
    assert len(jobs) == 1
    assert "Danone" in jobs[0].company


def test_nube_native_code_and_fields(monkeypatch):
    html = '''<article><h3>Engenharia Elétrica - 363260</h3><p>Vaga de Estágio</p><p>São Paulo | SP</p><p>Híbrido</p><p>R$ 3.000,00</p><a href="/detalhes-vaga/363260/vaga-de-estagio-em-engenharia-eletrica">Tenho interesse</a></article>'''
    monkeypatch.setattr(nube, "get_text", lambda *a, **k: html)
    jobs = nube.collect_nube({"show_incremental_stats": False})
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_job_id == "nube:363260"
    assert job.location == "São Paulo, SP"
    assert job.salary == "R$ 3.000,00"
    assert job.workplace_type == "hybrid"


def test_iel_public_card(monkeypatch):
    html = '''<article><h3>Estágio em Engenharia Elétrica</h3><span>Estágio 16/09/2026</span><span>GENESYS Manaus/AM Presencial R$ 900,00</span><a href="/AM/vaga/10753">Quero esta vaga</a></article>'''
    monkeypatch.setattr(iel, "get_text", lambda *a, **k: html)
    jobs = iel.collect_iel({"scopes": [{"state": "AM", "url": "https://carreiras.iel.org.br/AM"}], "show_incremental_stats": False})
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_job_id == "iel:AM:10753"
    assert job.title == "Estágio em Engenharia Elétrica"
    assert job.location == "Manaus, AM"
    assert job.published_at == "2026-09-16"


def test_cia_talentos_hydration_when_public(monkeypatch):
    html = '''<script type="application/json">{"jobs":[{"id":"abc","title":"Programa de Estágio ACME 2027","company":"ACME","city":"São Paulo, SP","url":"/vagas/acme"}]}</script>'''
    monkeypatch.setattr(cia_talentos, "get_text", lambda *a, **k: html)
    jobs = cia_talentos.collect_cia_talentos({"show_incremental_stats": False})
    assert len(jobs) == 1
    assert jobs[0].source_job_id == "cia_talentos:abc"


def test_superestagios_requires_explicit_public_pages(capsys):
    assert superestagios.collect_superestagios({}) == []
    assert "[SKIP]" in capsys.readouterr().out


def test_nube_parses_current_text_only_cards(monkeypatch):
    html = '''
    <div>Engenharia - 374203</div>
    <div>Vaga de Estágio</div>
    <div>Paulínia | SP</div>
    <div>Híbrido</div>
    <div>R$ 1.900,00</div>
    <button>Tenho interesse</button>
    <div>Administrativa - 375043</div>
    <div>Vaga de Aprendiz</div>
    <div>São Paulo | SP</div>
    <div>R$ 1.142,33</div>
    <button>Tenho interesse</button>
    '''
    monkeypatch.setattr(nube, "get_text", lambda *a, **k: html)
    jobs = nube.collect_nube({"show_incremental_stats": False})
    assert {job.source_job_id for job in jobs} == {
        "nube:374203",
        "nube:375043",
    }
    first = next(
        job for job in jobs if job.source_job_id == "nube:374203"
    )
    assert first.location == "Paulínia, SP"
    assert first.workplace_type == "hybrid"
    assert first.salary == "R$ 1.900,00"


def test_iel_enriches_public_detail(monkeypatch):
    listing = '''
    <a href="/AM/vaga/estagio/31458/estagio-em-engenharia-eletrica">
      Estágio 16/09/2026 Estágio em Engenharia Elé...
      GENESYS - SERVICOS TECNIC... Manaus/AM Presencial
      R$ 900,00 Quero esta vaga
    </a>
    '''
    detail = '''
    <h1>Estágio em Engenharia Elétrica</h1>
    <h2>Empresa:</h2><p>GENESYS - SERVICOS TECNICOS LTDA</p>
    <h2>Cidade:</h2><p>Manaus</p>
    <h2>Remuneração:</h2><p>R$ 900,00</p>
    <h2>Formato de trabalho:</h2><p>Presencial</p>
    '''
    monkeypatch.setattr(
        iel,
        "get_text",
        lambda url, *a, **k: detail if "/31458/" in url else listing,
    )
    jobs = iel.collect_iel({
        "scopes": [{
            "state": "",
            "url": "https://carreiras.iel.org.br/",
        }],
        "show_incremental_stats": False,
    })
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_job_id == "iel:AM:31458"
    assert job.title == "Estágio em Engenharia Elétrica"
    assert job.company == "GENESYS - SERVICOS TECNICOS LTDA"
    assert job.location == "Manaus, AM"
    assert job.salary == "R$ 900,00"
    assert job.workplace_type == "on-site"
