from collectors import jobs99


HTML = """
<html><body>
  <article>
    <a href="https://gruposmartfit.99jobs.com/vagas/492613-smart-fit-professor">
      <h3>Smart Fit | Professor de Educação Física</h3>
      <span>Assistente</span><span>Presencial</span>
      <span>São Luís, MA</span><span>SMARTFIT ESC DE GIN DANCA S.A</span>
      <span>4.33</span><span>Eu quero!</span>
    </a>
  </article>
  <article>
    <a href="/siemens-energy/jobs/507732-programa-de-estagio-pdt-siemens-energy-2027-1?utm_source=tagportal">
      <h3>Programa de Estágio PDT Siemens Energy 2027.1</h3>
      <span>Estágio</span><span>Híbrido</span><span>Não informado</span>
      <span>Siemens Energy</span><span>4.6</span><span>Eu quero!</span>
    </a>
  </article>
</body></html>
"""


def test_parser_accepts_jobs_and_vagas_urls():
    parsed = jobs99.parse_99jobs_html(HTML)
    assert {job.source_job_id for job in parsed} == {"492613", "507732"}
    assert {job.metadata["url_style"] for job in parsed} == {"jobs", "vagas"}


def test_parser_keeps_clean_title_company_location_and_modality():
    parsed = {job.source_job_id: job for job in jobs99.parse_99jobs_html(HTML)}

    smartfit = parsed["492613"]
    assert smartfit.title == "Smart Fit | Professor de Educação Física"
    assert smartfit.company == "SMARTFIT ESC DE GIN DANCA S.A"
    assert smartfit.location == "São Luís, MA"
    assert smartfit.workplace_type == "Presencial"

    siemens = parsed["507732"]
    assert siemens.title == "Programa de Estágio PDT Siemens Energy 2027.1"
    assert siemens.company == "Siemens Energy"
    assert siemens.employment_type == "Estágio"
    assert siemens.workplace_type == "Híbrido"
    assert "?" not in siemens.url


def test_collector_combines_entrypoints_and_deduplicates(monkeypatch):
    page_a = HTML
    page_b = """
    <article>
      <a href="https://www.99jobs.com/siemens-energy/jobs/507732-programa-de-estagio-pdt-siemens-energy-2027-1">
        <h3>Programa de Estágio PDT Siemens Energy 2027.1</h3>
        <span>Estágio</span><span>Híbrido</span><span>Não informado</span>
        <span>Siemens Energy</span><span>4.6</span><span>Eu quero!</span>
      </a>
    </article>
    <article>
      <a href="/engie/jobs/600001-programa-de-estagio-engie">
        <h3>Programa de Estágio ENGIE</h3>
        <span>Estágio</span><span>Presencial</span><span>Campinas - SP</span>
        <span>ENGIE</span><span>4.2</span><span>Eu quero!</span>
      </a>
    </article>
    """

    monkeypatch.setattr(jobs99, "ENTRYPOINTS", ("page-a", "page-b"))
    monkeypatch.setattr(jobs99, "SEARCH_TERMS", ())
    monkeypatch.setattr(jobs99, "get_text", lambda url: page_a if url == "page-a" else page_b)

    parsed = jobs99.collect_99jobs(max_jobs=20)
    assert {job.source_job_id for job in parsed} == {"492613", "507732", "600001"}


def test_search_url_uses_public_term_and_page_parameter():
    first = jobs99._search_page_url("estagio", 1)
    second = jobs99._search_page_url("engenharia elétrica", 2)
    assert "search%5Bterm%5D=estagio" in first
    assert "page=" not in first
    assert "search%5Bterm%5D=engenharia+el%C3%A9trica" in second
    assert "page=2" in second


def test_search_pagination_stops_when_page_repeats(monkeypatch):
    page = """
    <article><a href="/empresa/jobs/700001-estagio-engenharia">
      <h3>Estágio em Engenharia</h3><span>Estágio</span><span>Presencial</span>
      <span>São Carlos, SP</span><span>Empresa Teste</span><span>4.0</span><span>Eu quero!</span>
    </a></article>
    """
    calls = []
    monkeypatch.setattr(jobs99, "ENTRYPOINTS", ())
    monkeypatch.setattr(jobs99, "SEARCH_TERMS", ("estagio",))
    monkeypatch.setattr(jobs99, "MAX_PAGES_PER_SEARCH", 5)
    monkeypatch.setattr(jobs99, "MAX_GLOBAL_PAGES", 0)
    def fake_get_text(url):
        calls.append(url)
        return page
    monkeypatch.setattr(jobs99, "get_text", fake_get_text)
    parsed = jobs99.collect_99jobs(max_jobs=20)
    assert [job.source_job_id for job in parsed] == ["700001"]
    assert len(calls) == 2
    assert "page=2" in calls[-1]


def test_parser_accepts_external_opportunity_cards_and_keeps_useful_query():
    html = """
    <article>
      <a class="opportunity-card"
         href="https://carreiras.magazineluiza.com.br/job/123?jobId=ABC&utm_source=99jobs">
        <h3>VENDEDOR(A)</h3>
        <span>Pleno</span><span>Presencial</span><span>Campinas, SP</span>
        <span>Magazine Luiza</span><span>4.54</span><span>Eu quero!</span>
      </a>
    </article>
    """
    parsed = jobs99.parse_99jobs_html(html)
    assert len(parsed) == 1
    job = parsed[0]
    assert job.source_job_id.startswith("external-")
    assert job.company == "Magazine Luiza"
    assert job.location == "Campinas, SP"
    assert job.metadata["url_style"] == "external"
    assert job.metadata["external_destination"] is True
    assert "jobId=ABC" in job.url
    assert "utm_source" not in job.url


def test_parser_ignores_unrelated_external_navigation_links():
    html = """
    <nav><a href="https://example.com"><h3>Para empresas</h3></a></nav>
    <a href="https://linkedin.com/company/99jobs">LinkedIn</a>
    """
    assert jobs99.parse_99jobs_html(html) == []


def test_global_catalog_runs_after_strategic_searches(monkeypatch):
    strategic = """
    <article><a href="/empresa/jobs/800001-estagio"><h3>Estágio</h3>
    <span>Estágio</span><span>Presencial</span><span>São Carlos, SP</span>
    <span>Empresa A</span><span>4.0</span><span>Eu quero!</span></a></article>
    """
    broad1 = """
    <article><a href="/empresa/jobs/800002-analista"><h3>Analista</h3>
    <span>Júnior</span><span>Híbrido</span><span>Araraquara, SP</span>
    <span>Empresa B</span><span>4.0</span><span>Eu quero!</span></a></article>
    """
    broad2 = """
    <article><a href="/empresa/jobs/800003-assistente"><h3>Assistente</h3>
    <span>Assistente</span><span>Presencial</span><span>Campinas, SP</span>
    <span>Empresa C</span><span>4.0</span><span>Eu quero!</span></a></article>
    """
    calls = []
    monkeypatch.setattr(jobs99, "ENTRYPOINTS", ())
    monkeypatch.setattr(jobs99, "SEARCH_TERMS", ("estagio",))
    monkeypatch.setattr(jobs99, "MAX_PAGES_PER_SEARCH", 1)
    monkeypatch.setattr(jobs99, "MAX_GLOBAL_PAGES", 3)

    def fake_get_text(url):
        calls.append(url)
        if "search%5Bterm%5D=estagio" in url:
            return strategic
        if "page=2" in url:
            return broad2
        return broad1

    monkeypatch.setattr(jobs99, "get_text", fake_get_text)
    parsed = jobs99.collect_99jobs(max_jobs=3)
    assert {job.source_job_id for job in parsed} == {"800001", "800002", "800003"}
    assert any("search%5Bterm%5D=" in url for url in calls)


def test_global_pagination_stops_when_page_repeats(monkeypatch):
    page = """
    <article><a href="/empresa/jobs/900001-vaga"><h3>Vaga</h3>
    <span>Júnior</span><span>Presencial</span><span>São Paulo, SP</span>
    <span>Empresa</span><span>4.0</span><span>Eu quero!</span></a></article>
    """
    calls = []
    monkeypatch.setattr(jobs99, "ENTRYPOINTS", ())
    monkeypatch.setattr(jobs99, "SEARCH_TERMS", ())
    monkeypatch.setattr(jobs99, "MAX_GLOBAL_PAGES", 20)
    monkeypatch.setattr(jobs99, "get_text", lambda url: calls.append(url) or page)
    parsed = jobs99.collect_99jobs(max_jobs=100)
    assert [job.source_job_id for job in parsed] == ["900001"]
    assert len(calls) == 2
    assert "page=2" in calls[-1]
