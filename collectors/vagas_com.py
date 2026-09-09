import re
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.common import get_text
from models.job import Job

BASE = "https://www.vagas.com.br"


def collect_vagas_com(query: str, max_jobs: int = 40) -> list[Job]:
    slug = _slugify(query)
    url = f"{BASE}/vagas-de-{slug}"
    html = get_text(url)
    soup = BeautifulSoup(html, "html.parser")

    jobs: list[Job] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        match = re.search(r"/vagas/v(\d+)/", href)
        if not match:
            continue

        job_id = match.group(1)
        if job_id in seen:
            continue
        seen.add(job_id)

        title = _clean(anchor.get_text(" ", strip=True))
        if not title:
            continue

        card = _find_card(anchor)
        card_text = _clean(card.get_text(" ", strip=True)) if card else title
        company, location = _extract_company_location(card, title)

        jobs.append(
            Job(
                source="vagas_com",
                source_type="public_page",
                source_job_id=job_id,
                company=company or "Empresa não identificada",
                title=title,
                location=location,
                url=urljoin(BASE, href),
                description=card_text,
                employment_type="Estágio" if _is_internship(card_text, title) else None,
                metadata={"query": query, "search_url": url},
            )
        )

        if len(jobs) >= max_jobs:
            break

    return jobs


def _find_card(anchor):
    for tag in ("li", "article"):
        parent = anchor.find_parent(tag)
        if parent:
            return parent

    current = anchor
    for _ in range(6):
        current = current.parent
        if current is None:
            break
        text = _clean(current.get_text(" ", strip=True))
        if 30 < len(text) < 3500 and len(current.find_all(["h2", "h3"])) <= 10:
            return current
    return anchor.parent


def _extract_company_location(card, title):
    if not card:
        return "", ""

    strings = [_clean(x) for x in card.stripped_strings]
    strings = [x for x in strings if x]

    try:
        idx = strings.index(title)
    except ValueError:
        idx = 0

    nearby = strings[idx + 1: idx + 20]
    location = ""

    for text in nearby:
        if _looks_like_location(text):
            location = text
            break

    # Empresa: escolhe o primeiro texto próximo que passe por filtros básicos.
    # Isso evita o bug em que fragmentos como "em" eram tratados como empresa.
    company = ""
    for text in nearby:
        if _looks_like_company(text, title, location):
            company = text
            break

    if not location:
        text = _clean(card.get_text(" ", strip=True))
        m = re.search(r"([A-Za-zÀ-ÿ .'-]{2,60})\s*/\s*([A-Z]{2})", text)
        if m:
            location = f"{m.group(1).strip()} / {m.group(2)}"

    return company, location


def _looks_like_company(text: str, title: str, location: str) -> bool:
    low = _norm(text)
    if not low or len(low) < 3 or len(text) > 120:
        return False

    stop = {
        "em", "de", "da", "do", "das", "dos", "para", "por",
        "estagio", "estagio em", "vaga", "vagas", "publicidade",
        "mais relevantes", "mais recentes", "candidatar se", "candidatar-se",
        "descricao", "descricao da vaga", "requisitos", "beneficios",
        "remoto", "remota", "hibrido", "hibrida", "presencial",
    }
    if low in stop:
        return False
    if low == _norm(title) or (location and low == _norm(location)):
        return False
    if _looks_like_location(text):
        return False
    if re.search(r"\bR\$\s*\d", text, re.I):
        return False
    if re.search(r"\b(há|ha)\s+\d+\s+(dia|dias|hora|horas)\b", low):
        return False
    if re.fullmatch(r"\d+[+]?", low):
        return False
    return True


def _looks_like_location(text: str) -> bool:
    return bool(
        re.search(r"\b.+\s*/\s*[A-Z]{2}\b", text)
        or re.search(r"\b.+\s+-\s+[A-Z]{2}\b", text)
    )


def _is_internship(card_text: str, title: str) -> bool:
    joined = _norm(f"{title} {card_text[:500]}")
    return "estagio" in joined or "internship" in joined or re.search(r"\bintern\b", joined) is not None


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", (value or "").lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
