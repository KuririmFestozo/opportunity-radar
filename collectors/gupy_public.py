import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from collectors.common import get_text
from models.job import Job


DETAIL_HINTS = (
    "estagio", "estágio", "intern", "engenharia", "engineering",
    "eletric", "eletr", "hardware", "firmware", "embedded",
    "automacao", "automação", "energia", "power",
)


def collect_gupy_public(
    company_name: str,
    base_url: str,
    max_details: int = 20,
) -> list[Job]:
    html = get_text(base_url.rstrip("/") + "/")
    soup = BeautifulSoup(html, "html.parser")

    found: dict[str, Job] = {}

    # Estratégia principal: links públicos /jobs/<id>.
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        match = re.search(r"/jobs/(\d+)", href)
        if not match:
            continue

        job_id = match.group(1)
        title = _clean(anchor.get_text(" ", strip=True))
        if not title:
            title = f"Vaga Gupy {job_id}"

        container = _card_container(anchor)
        card_text = _clean(container.get_text(" ", strip=True)) if container else title
        location = _extract_location(card_text, title)

        found[job_id] = Job(
            source="gupy_public",
            source_type="public_page",
            source_job_id=job_id,
            company=company_name,
            title=title,
            location=location,
            url=urljoin(base_url.rstrip("/") + "/", href),
            description=card_text,
            employment_type="Estágio" if "estágio" in card_text.lower() else None,
        )

    # Fallback: algumas páginas colocam URLs em JSON/JS embarcado.
    if not found:
        for job_id in sorted(set(re.findall(r'/jobs/(\d+)', html))):
            found[job_id] = Job(
                source="gupy_public",
                source_type="public_page",
                source_job_id=job_id,
                company=company_name,
                title=f"Vaga Gupy {job_id}",
                location="",
                url=f"{base_url.rstrip('/')}/jobs/{job_id}?jobBoardSource=gupy_public_page",
            )

    jobs = list(found.values())

    # Buscamos detalhes apenas de vagas com título promissor ou,
    # em páginas pequenas, de todas as vagas. Isso evita centenas de requests.
    if len(jobs) <= max_details:
        candidates = jobs
    else:
        candidates = [
            job for job in jobs
            if any(term in job.title.lower() for term in DETAIL_HINTS)
        ][:max_details]

    for job in candidates:
        try:
            _enrich_detail(job)
        except Exception:
            # Falha em uma vaga não derruba o coletor inteiro.
            pass

    return jobs


def _enrich_detail(job: Job) -> None:
    html = get_text(job.url)
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if h1:
        title = _clean(h1.get_text(" ", strip=True))
        if title:
            job.title = title

    text = _clean(soup.get_text(" ", strip=True))
    if text:
        job.description = text[:12000]

    # O Gupy costuma exibir localidade no texto ou em metadados.
    if not job.location:
        loc = _find_meta(soup, "jobLocation")
        if loc:
            job.location = loc


def _find_meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find(attrs={"itemprop": name})
    return _clean(tag.get_text(" ", strip=True)) if tag else ""


def _card_container(anchor):
    for tag in ("li", "article"):
        parent = anchor.find_parent(tag)
        if parent:
            return parent
    current = anchor
    for _ in range(5):
        current = current.parent
        if current is None:
            break
        text = _clean(current.get_text(" ", strip=True))
        if 10 < len(text) < 1600:
            return current
    return anchor.parent


def _extract_location(card_text: str, title: str) -> str:
    remainder = card_text.replace(title, " ", 1).strip()
    match = re.search(
        r"([A-Za-zÀ-ÿ .'-]{2,50})\s*-\s*([A-Z]{2})(?:\s|$)",
        remainder,
    )
    if match:
        return f"{match.group(1).strip()} - {match.group(2)}"
    return ""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
