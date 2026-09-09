import re
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from collectors.common import get_text
from models.job import Job


URL = "https://www.99jobs.com/opportunities/search"

# A 99jobs mistura oportunidades no domínio principal (/jobs/<id>) com
# páginas white-label de clientes (/vagas/<id>) em subdomínios. A busca
# principal sozinha também favorece vagas recentes/genéricas, então usamos
# algumas coleções públicas como pontos de entrada complementares.
ENTRYPOINTS = (
    URL,
    "https://www.99jobs.com/collections/seu-proximo-estagio-ta-on",
    "https://www.99jobs.com/collections/trainee-para-ser-um-futuro-lider",
    "https://www.99jobs.com/collections/tech-mais-que-amigos-friends",
    "https://www.99jobs.com/collections/gigantes-do-mercado",
)

_JOB_PATH = re.compile(r"/(?:jobs|vagas)/(\d+)(?:[-/?#]|$)", re.IGNORECASE)


def collect_99jobs(max_jobs: int = 80) -> list[Job]:
    """Collect public 99jobs opportunities from multiple discovery pages.

    This intentionally stays low-frequency and only reads pages available to
    an unauthenticated candidate. No login, CAPTCHA or anti-bot mechanism is
    bypassed. Course/intent/location filtering remains local to Opportunity
    Radar (collect first, filter later).
    """
    found: dict[str, Job] = {}

    for entrypoint in ENTRYPOINTS:
        if len(found) >= max_jobs:
            break

        html = get_text(entrypoint)
        for job in parse_99jobs_html(html, entrypoint, max_jobs=max_jobs):
            existing = found.get(job.source_job_id)
            if existing is None or _quality(job) > _quality(existing):
                found[job.source_job_id] = job
            if len(found) >= max_jobs:
                break

    return list(found.values())[:max_jobs]


def parse_99jobs_html(
    html: str,
    page_url: str = URL,
    *,
    max_jobs: int = 200,
) -> list[Job]:
    """Parse one public 99jobs page without making network requests."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[Job] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        absolute = urljoin(page_url, href)
        job_id = _id_from_url(absolute)
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)

        title = _title_from_anchor(anchor)
        if not title or len(title) < 3:
            continue

        card = _find_card(anchor)
        card_text = _clean(card.get_text(" ", strip=True)) if card else title
        canonical = _canonical_url(absolute)

        jobs.append(
            Job(
                source="99jobs",
                source_type="public_page",
                source_job_id=job_id,
                company=_company_from_url_or_card(canonical, card_text, title),
                title=title,
                location=_extract_location(card_text),
                url=canonical,
                description=card_text,
                employment_type=_employment_type(card_text),
                workplace_type=_workplace(card_text),
                metadata={
                    "discovered_from": page_url,
                    "url_style": "vagas" if "/vagas/" in urlparse(canonical).path else "jobs",
                },
            )
        )

        if len(jobs) >= max_jobs:
            break

    return jobs


def _title_from_anchor(anchor) -> str:
    # Cards atuais normalmente têm o cargo em um heading dentro do link.
    heading = anchor.find(["h1", "h2", "h3", "h4"])
    if heading:
        title = _clean(heading.get_text(" ", strip=True))
        if title:
            return title

    # Alguns templates deixam o heading fora do <a>.
    card = _find_card(anchor)
    if card:
        heading = card.find(["h1", "h2", "h3", "h4"])
        if heading:
            title = _clean(heading.get_text(" ", strip=True))
            if title:
                return title

    return _clean(anchor.get_text(" ", strip=True))


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
        if 20 < len(text) < 2200:
            return current

    return anchor.parent


def _id_from_url(url: str) -> str:
    match = _JOB_PATH.search(urlsplit(url).path)
    return match.group(1) if match else ""


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _company_from_url_or_card(url: str, card_text: str, title: str) -> str:
    remainder = _clean(card_text.replace(title, " ", 1))

    # O card público costuma terminar com: localização + empresa + nota + CTA.
    company_match = re.search(
        r"(?:Não informado|[A-Za-zÀ-ÿ .'-]{2,60}(?:,|\s+-)\s*[A-Z]{2})\s+"
        r"(.{2,100}?)\s+\d(?:[.,]\d+)?\s+(?:Eu quero!?|Ver Oportunidade)\b",
        remainder,
        re.IGNORECASE,
    )
    if company_match:
        company = _clean(company_match.group(1))
        if company:
            return company

    host = urlparse(url).netloc.lower()
    if host and host not in {"99jobs.com", "www.99jobs.com"}:
        sub = host.split(".")[0]
        aliases = {
            "gruposmartfit": "Grupo Smart Fit",
            "vagasgrupodpsp": "Grupo DPSP",
            "carreiras": "99jobs",
        }
        return aliases.get(sub, sub.replace("-", " ").replace("_", " ").title())

    # Fallback para cards antigos que exibem a empresa em caixa alta.
    candidates = re.findall(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9 &.\-]{3,80}\b", remainder)
    ignored = {"ESTÁGIO", "TRAINEE", "PRESENCIAL", "REMOTO", "REMOTA", "HÍBRIDO", "HÍBRIDA"}
    candidates = [c for c in candidates if _clean(c).upper() not in ignored]
    if candidates:
        return _clean(candidates[-1])
    return "99jobs"


def _extract_location(text: str) -> str:
    # Cards aparecem tanto como "Campinas, SP" quanto "Campinas - SP".
    # Quando a modalidade está presente, a localização vem logo depois dela;
    # limitar a busca a esse trecho evita engolir título/nível junto da cidade.
    search_text = text
    low = text.lower()
    markers = ("presencial", "híbrido", "hibrido", "híbrida", "hibrida", "remoto", "remota")
    positions = [(low.rfind(marker), marker) for marker in markers if low.rfind(marker) >= 0]
    if positions:
        pos, marker = max(positions, key=lambda item: item[0])
        search_text = text[pos + len(marker):]

    match = re.search(
        r"([A-Za-zÀ-ÿ .'-]{2,60}?)\s*(?:,|-)\s*([A-Z]{2})\b",
        search_text,
    )
    if match:
        return f"{match.group(1).strip()}, {match.group(2)}"
    return ""


def _employment_type(text: str) -> str | None:
    low = text.lower()
    if "estágio" in low or "estagio" in low:
        return "Estágio"
    if "trainee" in low:
        return "Trainee"
    if "jovem aprendiz" in low or "aprendiz" in low:
        return "Aprendiz"
    if "júnior" in low or "junior" in low:
        return "Júnior"
    return None


def _workplace(text: str) -> str | None:
    low = text.lower()
    if "híbrida" in low or "hibrida" in low or "híbrido" in low or "hibrido" in low:
        return "Híbrido"
    if "remota" in low or "remoto" in low:
        return "Remoto"
    if "presencial" in low:
        return "Presencial"
    return None


def _quality(job: Job) -> int:
    return sum(
        [
            bool(job.title and not job.title.startswith("Vaga 99jobs")),
            bool(job.company and job.company != "99jobs"),
            bool(job.location),
            bool(job.employment_type),
            bool(job.workplace_type),
        ]
    )


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
