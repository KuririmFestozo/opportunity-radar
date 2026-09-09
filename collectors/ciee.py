import re

from bs4 import BeautifulSoup

from collectors.common import get_text
from models.job import Job


URL = "https://portal.ciee.org.br/quero-uma-vaga/"


def collect_ciee(max_jobs: int = 120) -> list[Job]:
    """
    Coleta a vitrine pública do CIEE e filtra posteriormente pelo score.
    A página pública não expõe todos os detalhes sem interação/login,
    por isso este conector funciona como uma camada complementar.
    """
    html = get_text(URL)
    soup = BeautifulSoup(html, "html.parser")
    text = _clean(soup.get_text(" ", strip=True))

    # Cada card público começa com código numérico e termina em "Ver detalhes".
    pattern = re.compile(
        r"(?P<code>\d{6,8})\s+Compartilhar\s+"
        r"(?P<type>Estágio|Estagio|Aprendiz|PCD|Processos Públicos)"
        r"\s+(?P<body>.*?)(?=Ver detalhes)",
        re.IGNORECASE,
    )

    jobs: list[Job] = []

    for match in pattern.finditer(text):
        code = match.group("code")
        opportunity_type = match.group("type")
        body = _clean(match.group("body"))

        title = _infer_title(body)
        location = _extract_location(body)

        jobs.append(
            Job(
                source="ciee",
                source_type="public_page",
                source_job_id=code,
                company="CIEE / empresa não identificada",
                title=title,
                location=location,
                url=f"{URL}?codigoVaga={code}",
                description=body,
                employment_type=opportunity_type,
                metadata={"public_listing": True},
            )
        )

        if len(jobs) >= max_jobs:
            break

    return jobs


def _infer_title(body: str) -> str:
    # O CIEE frequentemente não divulga o nome da empresa na vitrine.
    # Usamos área + natureza da atividade como título resumido.
    area_patterns = [
        r"(Engenharia[^R$]{0,80})",
        r"(Elétrica[^R$]{0,80})",
        r"(Eletrônica[^R$]{0,80})",
        r"(Automação[^R$]{0,80})",
        r"(Eletrotécnica[^R$]{0,80})",
    ]
    for pattern in area_patterns:
        m = re.search(pattern, body, re.IGNORECASE)
        if m:
            return _clean(m.group(1))[:140]
    return ("Estágio CIEE - " + body[:110]).strip()


def _extract_location(body: str) -> str:
    m = re.search(
        r"([A-Za-zÀ-ÿ .'-]{2,60})\s*-\s*([A-Za-zÀ-ÿ .'-]{2,60})\s*-\s*([A-Z]{2})\b",
        body,
    )
    if m:
        return f"{m.group(2).strip()} - {m.group(3)}"

    m = re.search(r"([A-Za-zÀ-ÿ .'-]{2,60})\s*-\s*([A-Z]{2})\b", body)
    if m:
        return f"{m.group(1).strip()} - {m.group(2)}"

    return ""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
