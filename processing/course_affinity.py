"""Explainable and bounded course-affinity scoring.

Scores are affinity/confidence bands, not hiring probabilities:
  90-100  explicit course/profession evidence
  70-89   strong specialization or explicit degree requirement
  45-69   meaningful related area
  20-44   weak/partial evidence
  0-19    incidental/noise (normally collapsed to zero)
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from models.job import Job
from processing.text import normalize


ROLE_TOKENS = frozenset({
    "engineer", "engineering", "intern", "internship", "estagiario", "estagiaria",
    "estagio", "designer", "technician", "tecnico", "tecnica", "specialist",
    "especialista", "developer", "desenvolvedor", "desenvolvedora",
})

EDUCATION_TERMS = (
    "degree", "bachelor", "bachelors", "major", "student", "students", "undergraduate",
    "graduacao", "graduando", "graduanda", "cursando", "matriculado", "matriculada",
    "matriculados", "matriculadas", "formacao", "ensino superior",
    "universidade", "university", "college", "academic", "curso", "cursos", "curso superior",
)

AEROSPACE_TERMS = (
    "aircraft", "aerospace", "uav", "uas", "avionics", "flight", "airframe",
    "aerostructure", "aerostructures",
)

MEDIA_PRODUCTION_TERMS = (
    "audiovisual", "video", "creative", "content", "conteudo", "cinema", "televisao",
    "tv", "fotografia", "media",
)


@dataclass(frozen=True)
class CourseRule:
    label: str
    direct: tuple[str, ...]
    strong: tuple[str, ...]
    weak: tuple[str, ...]
    course_terms: tuple[str, ...]
    profession_terms: tuple[str, ...] = ()
    discipline_tokens: frozenset[str] = frozenset()
    weak_body: tuple[str, ...] = ()
    strong_score: int = 74


RULES: dict[str, CourseRule] = {
    "electrical_engineering": CourseRule(
        label="Engenharia Elétrica",
        direct=(
            "engenharia eletrica", "engenheiro eletrico", "engenheira eletrica",
            "electrical engineering", "electrical engineer",
            "engenharia eletronica", "engenheiro eletronico", "engenheira eletronica",
            "electronics engineering", "electronics engineer",
        ),
        discipline_tokens=frozenset({"electrical", "eletrica", "eletrico", "electronics", "eletronica", "eletronico"}),
        strong=(
            "avionics", "power electronics", "power system", "power systems", "electrical system",
            "electrical systems", "embedded", "firmware", "hardware", "pcb", "fpga", "asic", "rf",
            "instrumentation", "instrumentacao", "industrial automation", "automacao industrial",
            "control system", "control systems",
        ),
        weak=("battery", "bateria", "robotics", "robotica", "telecom", "semiconductor"),
        course_terms=("engenharia eletrica", "electrical engineering", "engenharia eletronica", "electronics engineering"),
        profession_terms=("engenheiro eletrico", "engenheira eletrica", "electrical engineer", "engenheiro eletronico", "engenheira eletronica", "electronics engineer"),
        weak_body=("battery", "bateria", "telecom", "semiconductor"),
    ),
    "computer_science": CourseRule(
        label="Ciência da Computação",
        direct=(
            "ciencia da computacao", "computer science", "engenharia de software", "software engineering",
            "software engineer", "software developer", "desenvolvedor", "desenvolvedora", "programmer",
        ),
        discipline_tokens=frozenset({"software"}),
        strong=(
            "backend", "back end", "frontend", "front end", "full stack", "fullstack", "devops", "cloud",
            "cybersecurity", "seguranca da informacao", "computer vision", "machine learning", "ai engineer",
            "artificial intelligence", "inteligencia artificial", "data engineering", "systems administrator",
            "system administrator", "web developer", "mobile developer", "ui engineer",
        ),
        weak=("python", "java", "javascript", "typescript", "c++", "rust", "sql", "database"),
        course_terms=("ciencia da computacao", "computer science", "engenharia de software", "software engineering"),
        profession_terms=("software engineer", "software developer", "desenvolvedor", "desenvolvedora", "programmer"),
        weak_body=("python", "java", "javascript", "typescript", "c++", "rust", "sql", "database"),
    ),
    "mechanical_engineering": CourseRule(
        label="Engenharia Mecânica",
        direct=(
            "engenharia mecanica", "engenheiro mecanico", "engenheira mecanica",
            "mechanical engineering", "mechanical engineer",
        ),
        discipline_tokens=frozenset({"mechanical", "mecanica", "mecanico"}),
        strong=(
            "mechanical design", "thermal", "hydraulic", "hydraulics", "fluid", "fluids", "aerostructure",
            "aerostructures", "propulsion", "hvac", "thermodynamics", "structural analysis",
            "structures engineer", "structural engineer",
        ),
        weak=("cad", "cae", "solidworks", "catia", "ansys", "manufacturing", "aerospace", "automotive"),
        course_terms=("engenharia mecanica", "mechanical engineering"),
        profession_terms=("engenheiro mecanico", "engenheira mecanica", "mechanical engineer"),
        weak_body=("cad", "cae", "solidworks", "catia", "ansys"),
    ),
    "civil_engineering": CourseRule(
        label="Engenharia Civil",
        direct=("engenharia civil", "engenheiro civil", "engenheira civil", "civil engineering", "civil engineer"),
        discipline_tokens=frozenset({"civil"}),
        strong=(
            "structural engineering", "structural engineer", "construction", "construcao", "infrastructure",
            "infraestrutura", "geotechnical", "geotecnia", "bim", "revit", "planejamento de obras",
        ),
        weak=("autocad", "structure", "structures", "estrutura", "estruturas", "orcamento", "obras"),
        course_terms=("engenharia civil", "civil engineering"),
        profession_terms=("engenheiro civil", "engenheira civil", "civil engineer"),
        weak_body=("bim", "revit", "autocad", "geotechnical", "geotecnia"),
    ),
    "production_engineering": CourseRule(
        label="Engenharia de Produção",
        direct=(
            "engenharia de producao", "engenheiro de producao", "engenheira de producao",
            "production engineering", "production engineer", "industrial engineering", "industrial engineer",
        ),
        strong=(
            "manufacturing engineer", "manufacturing engineering", "process engineer", "quality engineer",
            "supply chain", "logistica", "logistics", "melhoria continua", "continuous improvement", "lean", "six sigma",
        ),
        weak=("operations", "operacoes", "quality", "qualidade", "planning", "planejamento", "processo", "processos"),
        course_terms=("engenharia de producao", "production engineering", "industrial engineering"),
        profession_terms=("engenheiro de producao", "engenheira de producao", "production engineer", "industrial engineer"),
        weak_body=("lean", "six sigma", "logistica", "logistics", "melhoria continua", "continuous improvement"),
        strong_score=68,
    ),
    "administration": CourseRule(
        label="Administração",
        direct=("administracao", "business administration"),
        strong=(
            "finance", "financas", "financial", "accounting", "contabilidade", "contabil", "marketing", "sales", "vendas",
            "human resources", "recursos humanos", "people operations", "procurement", "compras", "business development",
            "commercial", "comercial", "strategy", "estrategia",
        ),
        weak=("operations", "operacoes", "business", "negocios", "management", "gestao"),
        course_terms=("administracao", "business administration"),
        weak_body=("finance", "financas", "accounting", "marketing", "human resources", "recursos humanos", "procurement"),
        strong_score=70,
    ),
    "data_science": CourseRule(
        label="Ciência de Dados",
        direct=(
            "ciencia de dados", "cientista de dados", "data science", "data scientist",
            "machine learning engineer", "ml engineer",
        ),
        strong=(
            "machine learning", "deep learning", "computer vision", "nlp", "artificial intelligence",
            "inteligencia artificial", "ai engineer", "data analytics", "analytics engineer", "data analyst",
            "analista de dados", "data engineer", "engenheiro de dados", "engenheira de dados", "business intelligence", "bi",
        ),
        weak=("python", "sql", "statistics", "estatistica", "analytics"),
        course_terms=("ciencia de dados", "data science"),
        profession_terms=("cientista de dados", "data scientist", "machine learning engineer", "ml engineer"),
        weak_body=("sql", "statistics", "estatistica", "analytics"),
    ),
}

def _canon_term(value: str) -> str:
    value = normalize(value)
    value = re.sub(r"[^a-z0-9+#]+", " ", value)
    return " ".join(value.split())


# Canonicalize the static vocabulary once, not for every vacancy.
_RULE_TERMS: dict[str, dict[str, tuple[str, ...]]] = {}
for _course_id, _rule in RULES.items():
    _RULE_TERMS[_course_id] = {
        "direct": tuple(_canon_term(x) for x in _rule.direct),
        "strong": tuple(_canon_term(x) for x in _rule.strong),
        "weak": tuple(_canon_term(x) for x in _rule.weak),
        "course": tuple(_canon_term(x) for x in _rule.course_terms),
        "profession": tuple(_canon_term(x) for x in _rule.profession_terms),
        "weak_body": tuple(_canon_term(x) for x in _rule.weak_body),
    }

_EDUCATION_TERMS = tuple(_canon_term(x) for x in EDUCATION_TERMS)
_AEROSPACE_TERMS = tuple(_canon_term(x) for x in AEROSPACE_TERMS)
_MEDIA_PRODUCTION_TERMS = tuple(_canon_term(x) for x in MEDIA_PRODUCTION_TERMS)


def score_course_affinities(job: Job) -> tuple[dict[str, int], dict[str, list[str]]]:
    title = _clean(job.title)
    body = _clean(job.description)
    title_levels = {course_id: _title_level(title, course_id) for course_id in RULES}

    scores: dict[str, int] = {}
    reasons: dict[str, list[str]] = {}
    for course_id, rule in RULES.items():
        score, why = _score_one(course_id, rule, title, body, title_levels)
        scores[course_id] = score
        if score >= 35 and why:
            reasons[course_id] = why
    return scores, reasons


def _score_one(
    course_id: str,
    rule: CourseRule,
    title: str,
    body: str,
    title_levels: dict[str, int],
) -> tuple[int, list[str]]:
    terms = _RULE_TERMS[course_id]
    level = title_levels[course_id]
    direct_body = _present(body, terms["course"])
    profession_body = _present(body, terms["profession"])
    strong_body = _present(body, terms["strong"])
    weak_body = _present(body, terms["weak_body"])
    education = _education_match(body, terms["course"])
    why: list[str] = []

    if level == 3:
        score = 94
        why.append("curso/profissão explícita no título")
    elif level == 2:
        score = rule.strong_score
        why.append("especialidade fortemente ligada ao curso no título")
    elif level == 1:
        score = 46
        why.append("área relacionada no título")
    else:
        score = 0

    if education:
        score = max(score, 88)
        why.append("curso citado em requisito/formação")
    elif profession_body:
        score = max(score, 62)
        why.append("profissão da área descrita na vaga")
    elif direct_body:
        score = max(score, 46)
        why.append("curso citado na descrição")

    if strong_body:
        score = max(score, min(56, 28 + 7 * min(4, len(strong_body))))
        if level == 0 and not education and not profession_body:
            why.append("competências centrais da área na descrição")

    if weak_body:
        score = max(score, min(18, 6 + 3 * min(4, len(weak_body))))

    if level >= 2 and (direct_body or profession_body or strong_body):
        score = min(99, score + min(5, 2 * bool(direct_body or profession_body) + len(strong_body)))
    elif level == 1 and strong_body:
        score = min(68, score + min(8, 2 * len(strong_body)))

    other_max = max((value for key, value in title_levels.items() if key != course_id), default=0)
    if level == 0 and other_max >= 2 and not education:
        score = min(score, 28)
        if score >= 20:
            why.append("título aponta mais fortemente para outra área")
    elif level == 1 and other_max == 3 and not education:
        score = min(score, 48)

    if course_id == "civil_engineering" and level < 3 and _contains_any_phrase(f"{title} {body}", _AEROSPACE_TERMS):
        score = min(score, 30)

    if course_id == "production_engineering" and level < 3 and _contains_any_phrase(title, _MEDIA_PRODUCTION_TERMS):
        score = min(score, 15)

    if level == 0 and not education and score < 20:
        score = 0
        why = []

    return max(0, min(100, int(round(score)))), list(dict.fromkeys(why))[:3]


def _title_level(title: str, course_id: str) -> int:
    rule = RULES[course_id]
    terms = _RULE_TERMS[course_id]
    if _present(title, terms["direct"]):
        return 3
    if rule.discipline_tokens and _near_tokens(title, rule.discipline_tokens, ROLE_TOKENS, distance=3):
        return 3
    if _present(title, terms["strong"]):
        return 2
    if _present(title, terms["weak"]):
        return 1
    return 0


def _education_match(body: str, course_terms: tuple[str, ...]) -> bool:
    padded = f" {body} "
    for term in course_terms:
        needle = f" {term} "
        start = 0
        while True:
            index = padded.find(needle, start)
            if index < 0:
                break
            context = padded[max(0, index - 180): min(len(padded), index + len(needle) + 180)]
            if _contains_any_phrase(context, _EDUCATION_TERMS):
                return True
            start = index + 1
    return False


def _near_tokens(text: str, left: frozenset[str], right: frozenset[str], *, distance: int) -> bool:
    tokens = text.split()
    left_positions = [i for i, token in enumerate(tokens) if token in left]
    right_positions = [i for i, token in enumerate(tokens) if token in right]
    return any(abs(a - b) <= distance for a in left_positions for b in right_positions)


def _present(text: str, terms: tuple[str, ...]) -> list[str]:
    padded = f" {text} "
    return [term for term in terms if f" {term} " in padded]


def _contains_any_phrase(text: str, terms: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(f" {term} " in padded for term in terms)


def _clean(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = normalize(value)
    value = re.sub(r"[^a-z0-9+#]+", " ", value)
    return " ".join(value.split())
