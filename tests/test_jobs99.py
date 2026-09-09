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
    def fake_get_text(url):
        calls.append(url)
        return page
    monkeypatch.setattr(jobs99, "get_text", fake_get_text)
    parsed = jobs99.collect_99jobs(max_jobs=20)
    assert [job.source_job_id for job in parsed] == ["700001"]
    assert len(calls) == 2
    assert "page=2" in calls[-1]
