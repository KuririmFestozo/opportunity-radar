"""Checkpoint 2.9: public Brazilian internship/entry-level sources."""

EARLY_CAREER_SOURCES = [
    {
        "id": "walljobs", "name": "WallJobs", "collector": "walljobs", "enabled": True,
        "list_url": "https://app.walljobs.com.br/vagas", "fallback_url": "https://app.walljobs.com.br/", "max_jobs": 500,
    },
    {
        "id": "cia_estagios", "name": "Companhia de Estágios", "collector": "cia_estagios", "enabled": True,
        "list_url": "https://www.ciadeestagios.com.br/vagas-de-estagio/", "max_jobs": 200, "coverage": "public_programs_only",
    },
    {
        "id": "nube", "name": "Nube", "collector": "nube", "enabled": True,
        "list_url": "https://www.nube.com.br/estudantes/vagas/busca-avancada-saida", "max_jobs": 1500,
    },
    {
        "id": "iel", "name": "IEL Carreiras", "collector": "iel", "enabled": True,
        "scopes": [{"state": "", "url": "https://carreiras.iel.org.br/"}], "max_jobs": 2000,
    },
    {
        "id": "cia_talentos", "name": "Cia de Talentos", "collector": "cia_talentos", "enabled": False,
        "list_url": "https://ciadetalentos.com.br/", "max_jobs": 500,
        "disabled_reason": "Painel público dinâmico; contrato público estável de catálogo ainda não confirmado sem autenticação.",
    },
    {
        "id": "superestagios", "name": "Super Estágios", "collector": "superestagios", "enabled": True,
        "list_pages": [{"url": "https://www.superestagios.com.br/vagas/engenharia", "city": ""}],
        "max_jobs": 0, "coverage": "public_national_engineering",
    },
]

EARLY_CAREER_SOURCES.extend([
    {
        "id": "taqe", "name": "TAQE", "collector": "taqe", "enabled": True,
        "list_url": "https://vagas.taqe.com.br/", "max_jobs": 0,
    },
    {
        "id": "bettha", "name": "Bettha", "collector": "bettha", "enabled": True,
        "list_url": "https://www.bettha.com/vagas", "max_jobs": 0,
    },
    {
        "id": "matchbox", "name": "Matchbox Brasil", "collector": "matchbox", "enabled": True,
        "list_url": "https://matchboxbrasil.com/talentos/", "max_jobs": 0,
    },
])

for _source in EARLY_CAREER_SOURCES:
    if _source.get("enabled", True):
        _source["max_jobs"] = 0
