from collectors import jobs99
from models.job import Job
from processing.classification import classify_job
from processing.text import contains_any


def test_word_matching_does_not_match_intern_inside_international():
    assert contains_any("International EOR", ["intern"]) == []
    assert contains_any("Software Intern", ["intern"]) == ["intern"]


def test_international_employment_type_is_not_an_internship():
    job = Job(
        source="lever", source_job_id="x", company="Example",
        title="Business Development Lead", location="London",
        url="https://example.com/x", description="International business role.",
        employment_type="International EOR",
    )
    classify_job(job)
    assert "internship" not in job.detected_intents


def test_99jobs_card_is_scoped_to_one_opportunity_and_siemens_is_not_bluefit():
    html = """
    <section>
      <a class="opportunity-card" href="https://bluefit.99jobs.com/vagas/509057-estagio">
        <h3>Estágio em Educação Física</h3><span>Estágio</span><span>Presencial</span>
        <span>Anápolis, GO</span><span>BLUEFIT ACADEMIAS</span><span>3.0</span><span>Eu quero!</span>
      </a>
      <a class="opportunity-card" href="https://99jobs.com/siemens-energy/jobs/507732-programa-de-estagio-pdt-siemens-energy-2027-1">
        <h3>Programa de Estágio PDT Siemens Energy 2027.1</h3><span>Estágio</span><span>Híbrido</span>
        <span>Não informado</span><span>Siemens Energy</span><span>4.6</span><span>Eu quero!</span>
      </a>
    </section>
    """
    parsed = jobs99.parse_99jobs_html(html)
    assert len(parsed) == 2
    siemens = next(job for job in parsed if job.source_job_id == "507732")
    assert siemens.company == "Siemens Energy"
    assert "BLUEFIT" not in siemens.description
    assert "Anápolis" not in siemens.description
    assert siemens.employment_type == "Estágio"
    assert siemens.metadata["source_level"] == "Estágio"


def test_99jobs_source_level_is_a_strong_intent_signal():
    job = Job(
        source="99jobs", source_job_id="507732", company="Siemens Energy",
        title="Programa PDT 2027.1", location="",
        url="https://99jobs.com/siemens-energy/jobs/507732-programa",
        description="", employment_type="Estágio",
        metadata={"source_level": "Estágio"},
    )
    classify_job(job)
    assert "internship" in job.detected_intents


def test_99jobs_nearby_builds_city_and_intent_queries(monkeypatch):
    calls = []
    html = """
    <a class="opportunity-card" href="/empresa/jobs/700001-estagio">
      <h3>Estágio em Engenharia</h3><span>Estágio</span><span>Presencial</span>
      <span>São Carlos, SP</span><span>Empresa Teste</span><span>4.0</span><span>Eu quero!</span>
    </a>
    """
    monkeypatch.setattr(jobs99, "get_text", lambda url: calls.append(url) or html)
    parsed = jobs99.collect_99jobs_nearby(
        ["São Carlos", "Araraquara"], intent="internship",
        max_cities=2, max_pages_per_query=1, max_jobs=20,
    )
    assert parsed
    decoded = " ".join(calls).replace("+", " ").lower()
    assert "estagio" in decoded
    assert len(calls) == 2
