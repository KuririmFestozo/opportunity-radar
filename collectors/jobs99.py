import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from collectors.common import get_text
from models.job import Job


URL = "https://www.99jobs.com/opportunities/search"


def collect_99jobs(max_jobs: int = 80) -> list[Job]:
    """
    Coleta oportunidades visíveis na página pública de busca da 99jobs.
    O filtro de Engenharia Elétrica é aplicado pelo score local.
    """
    html = get_text(URL)
    soup = BeautifulSoup(html, "html.parser")

    jobs: list[Job] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if "/jobs/" not in href:
            continue

        absolute = urljoin(URL, href)
        if absolute in seen:
            continue
        seen.add(absolute)

        title = _clean(anchor.get_text(" ", strip=True))
        if not title or len(title) < 3:
            continue

        card = _find_card(anchor)
        card_text = _clean(card.get_text(" ", strip=True)) if card else title

        job_id = _id_from_url(absolute)
        company = _company_from_url_or_card(absolute, card_text, title)
        location = _extract_location(card_text)

        jobs.append(
            Job(
                source="99jobs",
                source_type="public_page",
                source_job_id=job_id or absolute,
                company=company,
                title=title,
                location=location,
                url=absolute,
                description=card_text,
                employment_type=_employment_type(card_text),
                workplace_type=_workplace(card_text),
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
        if 20 < len(text) < 1800:
            return current

    return anchor.parent


def _id_from_url(url: str) -> str:
    m = re.search(r"/jobs/(\d+)", url)
    return m.group(1) if m else ""


def _company_from_url_or_card(url: str, card_text: str, title: str) -> str:
    host = urlparse(url).netloc.lower()
    if host and host not in {"99jobs.com", "www.99jobs.com"}:
        sub = host.split(".")[0]
        return sub.replace("-", " ").replace("_", " ").title()

    remainder = card_text.replace(title, " ", 1)
    # Várias cartas exibem empresa em caixa alta.
    candidates = re.findall(r"\b[A-Z][A-Z0-9 &.\-]{3,80}\b", remainder)
    if candidates:
        return _clean(candidates[-1])
    return "99jobs"


def _extract_location(text: str) -> str:
    m = re.search(
        r"([A-Za-zÀ-ÿ .'-]{2,60}),\s*([A-Z]{2})\b",
        text,
    )
    if m:
        return f"{m.group(1).strip()}, {m.group(2)}"
    return ""


def _employment_type(text: str) -> str | None:
    low = text.lower()
    if "estágio" in low or "estagio" in low:
        return "Estágio"
    if "trainee" in low:
        return "Trainee"
    return None


def _workplace(text: str) -> str | None:
    low = text.lower()
    for word in ("remota", "remoto", "híbrida", "hibrida", "presencial"):
        if word in low:
            return word.capitalize()
    return None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
