from collectors.bettha import _parse as parse_bettha
from collectors.cargill import _parse_page as parse_cargill_page
from collectors.matchbox import _parse as parse_matchbox
from collectors.taqe import _parse as parse_taqe
from config.additional_ats import SMARTRECRUITERS_BOARDS, WORKDAY_BOARDS
from config.catalogs import COURSES
from config.profiles import PROFILES
from models.job import Job
from processing.classification import classify_job
from processing.collection_planner import build_collection_queries


def make_job(title, description=""):
    return Job(
        source="test",
        source_job_id=title,
        company="Example",
        title=title,
        location="",
        url="https://example.test",
        description=description,
    )


def test_chemical_engineering_title():
    job = make_job("Estágio em Engenharia Química")
    classify_job(job)
    assert job.course_scores["chemical_engineering"] >= 90


def test_chemical_engineering_requirement():
    job = make_job(
        "Engineering Intern",
        "Candidates must be pursuing Chemical Engineering / Engenharia Química.",
    )
    classify_job(job)
    assert job.course_scores["chemical_engineering"] >= 85


def test_new_engineering_courses_exist():
    expected = {
        "chemical_engineering",
        "materials_engineering",
        "computer_engineering",
        "physics_engineering",
        "agronomic_engineering",
        "environmental_engineering",
        "food_engineering",
        "forestry_engineering",
    }
    assert expected <= set(COURSES)


def test_new_profiles_exist():
    assert "chemical_engineering_internship_br" in PROFILES
    assert "ufscar_engineering_internship_br" in PROFILES


def test_unlimited_planner_includes_chemical_and_materials():
    queries = build_collection_queries(0)
    assert "estagio engenharia química" in queries
    assert "estagio engenharia de materiais" in queries
    assert len(queries) > 60


def test_new_corporate_boards_exist():
    workday = {row["id"] for row in WORKDAY_BOARDS if row.get("enabled", True)}
    smart = {row["id"] for row in SMARTRECRUITERS_BOARDS if row.get("enabled", True)}

    assert {"dow", "airliquide", "jj", "bakerhughes"} <= workday
    assert {"syngenta", "sgs", "wabtec"} <= smart


def test_taqe_parser():
    html = """
    <article>
      <h2>Rede Cidadã: Estágio</h2>
      <h5>Estágio em Engenharia Química - 12345</h5>
      <span>Campinas</span><span>R$ 1.500,00</span><span>Estágio</span>
      <a href="/rede/12345">Saiba Mais</a>
    </article>
    """
    jobs = parse_taqe(html, "https://vagas.taqe.com.br/")
    assert len(jobs) == 1
    assert jobs[0].employment_type == "internship"


def test_bettha_parser():
    html = """
    <article>
      <img alt="Logo da Givaudan">
      <h3>Estágio em Engenharia e Projetos – Givaudan</h3>
      <span>Estágio</span>
      <a href="/vaga/teste">Candidatar-se</a>
    </article>
    """
    jobs = parse_bettha(html, "https://www.bettha.com/vagas")
    assert len(jobs) == 1
    assert jobs[0].company == "Givaudan"


def test_matchbox_parser_ignores_closed():
    html = """
    <div>
      <a href="/aberto">Programa de Estágio Química 2027 Inscreva-se</a>
      <a href="/fechado">Programa de Estágio Antigo Inscrições encerradas</a>
    </div>
    """
    jobs = parse_matchbox(html, "https://matchboxbrasil.com/talentos/")
    assert len(jobs) == 1


def test_cargill_follows_next_link():
    html = """
    <ul>
      <li><a href="/job/test/123">Chemical Engineering Intern</a></li>
    </ul>
    <a rel="next" href="/en/search-jobs?p=2">Next</a>
    """
    jobs, next_url = parse_cargill_page(
        html,
        "https://careers.cargill.com/en/search-jobs",
    )
    assert len(jobs) == 1
    assert next_url == "https://careers.cargill.com/en/search-jobs?p=2"
