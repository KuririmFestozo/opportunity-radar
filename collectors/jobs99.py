import hashlib
import re
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlsplit,
    urlunsplit,
)

from bs4 import BeautifulSoup

from collectors.common import get_text
from models.job import Job


URL = "https://www.99jobs.com/opportunities/search"
FILTERED_URL = "https://www.99jobs.com/opportunities/filtered_search"

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
# Buscas estratégicas entram primeiro para garantir boa cobertura de programas
# de entrada. Depois o feed amplo completa a base sem depender de curso/perfil.
SEARCH_TERMS = (
    "estagio",
    "trainee",
    "jovem aprendiz",
    "junior",
    "engenharia",
    "tecnologia",
    "software",
    "dados",
    "manutencao",
    "administracao",
)

MAX_PAGES_PER_SEARCH = 4
REGIONAL_INTENT_TERMS = {
    "internship": ("estagio",),
    "summer_internship": (
        "estagio de ferias",
        "estagio de verao",
        "programa de ferias",
        "programa de verao",
        "summer internship",
    ),
    "seasonal_job": ("trabalho de ferias", "trabalho temporario de verao", "summer job"),
    "trainee": ("trainee",),
    "apprentice": ("jovem aprendiz",),
    "entry_level": ("junior",),
}
REGIONAL_DEFAULT_TERMS = ("estagio", "trainee", "jovem aprendiz", "junior")
# O catálogo público tinha ~4,5 mil oportunidades em 2026-09. A ideia não é
# martelar todas as páginas: este teto permite aproximar a 99jobs do volume da
# Gupy, e max_jobs encerra antes quando o alvo já foi atingido.
MAX_GLOBAL_PAGES = 150

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def collect_99jobs(max_jobs: int = 2500) -> list[Job]:
    """Collect a broad public sample of current 99jobs opportunities.

    Strategy:
      1. Editorial entrypoints, for high-value internship/trainee programs.
      2. Strategic public searches, to reinforce entry-level coverage.
      3. Broad paginated catalog crawl until max_jobs is reached.

    Only unauthenticated public pages are read. We stop on repeated pages, so a
    site-side pagination change does not create an endless request loop. Course,
    intent and location filtering remains local (collect first, filter later).
    """
    found: dict[str, Job] = {}

    # 1) Feed geral + coleções editoriais públicas.
    for entrypoint in ENTRYPOINTS:
        if len(found) >= max_jobs:
            break
        _merge_jobs(found, _fetch_page_jobs(entrypoint, max_jobs), max_jobs)

    # 2) Buscas amplas por intenção/área, com paginação defensiva.
    for term in SEARCH_TERMS:
        if len(found) >= max_jobs:
            break
        _collect_pages(
            found,
            lambda page, term=term: _search_page_url(term, page),
            MAX_PAGES_PER_SEARCH,
            max_jobs,
        )

    # 3) Catálogo amplo: traz oportunidades independentemente de curso/termo.
    # Isso faz a 99jobs participar do dashboard em volume, como a Gupy.
    if len(found) < max_jobs:
        _collect_pages(
            found,
            _global_page_url,
            MAX_GLOBAL_PAGES,
            max_jobs,
        )

    return list(found.values())[:max_jobs]



def collect_99jobs_nearby(
    city_names: list[str],
    *,
    intent: str | None = None,
    max_cities: int = 6,
    max_pages_per_query: int = 1,
    max_jobs: int = 400,
) -> list[Job]:
    """Focused public 99jobs searches for cities around the requested point."""
    found: dict[str, Job] = {}
    terms = REGIONAL_INTENT_TERMS.get(intent or "", REGIONAL_DEFAULT_TERMS)

    for city in city_names[: max(1, max_cities)]:
        for term in terms:
            if len(found) >= max_jobs:
                return list(found.values())[:max_jobs]
            query = f"{term} {city}".strip()
            sequence_ids: set[str] = set()
            for page in range(1, max(1, max_pages_per_query) + 1):
                page_jobs = _fetch_page_jobs(_search_page_url(query, page), max_jobs)
                page_ids = {job.source_job_id for job in page_jobs}
                if not page_ids:
                    break
                if page > 1 and page_ids <= sequence_ids:
                    break
                for job in page_jobs:
                    job.metadata["regional_query"] = query
                _merge_jobs(found, page_jobs, max_jobs)
                sequence_ids |= page_ids
                if len(found) >= max_jobs:
                    break

    return list(found.values())[:max_jobs]

def _collect_pages(found, url_builder, max_pages: int, max_jobs: int) -> None:
    sequence_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        if len(found) >= max_jobs:
            break

        page_jobs = _fetch_page_jobs(url_builder(page), max_jobs)
        page_ids = {job.source_job_id for job in page_jobs}

        if not page_ids:
            break
        # Se a 99jobs ignorar page=N e repetir a página, não insistimos.
        if page > 1 and page_ids <= sequence_ids:
            break

        _merge_jobs(found, page_jobs, max_jobs)
        sequence_ids |= page_ids


def _search_page_url(term: str, page: int = 1) -> str:
    params = {"search[term]": term, "utf8": "✓"}
    if page > 1:
        params["page"] = page
    return f"{FILTERED_URL}?{urlencode(params)}"


def _global_page_url(page: int = 1) -> str:
    params = {"search[term]": "", "utf8": "✓"}
    if page > 1:
        params["page"] = page
    return f"{FILTERED_URL}?{urlencode(params)}"


def _fetch_page_jobs(page_url: str, max_jobs: int) -> list[Job]:
    try:
        html = get_text(page_url)
    except Exception:
        # Uma consulta instável não derruba toda a fonte.
        return []
    return parse_99jobs_html(html, page_url, max_jobs=max_jobs)


def _merge_jobs(found: dict[str, Job], jobs: list[Job], max_jobs: int) -> int:
    added = 0
    for job in jobs:
        existing = found.get(job.source_job_id)
        if existing is None:
            found[job.source_job_id] = job
            added += 1
        elif _quality(job) > _quality(existing):
            found[job.source_job_id] = job

        if len(found) >= max_jobs:
            break
    return added


def parse_99jobs_html(
    html: str,
    page_url: str = URL,
    *,
    max_jobs: int = 3000,
) -> list[Job]:
    """Parse one public 99jobs page without making network requests."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[Job] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue

        absolute = urljoin(page_url, href)
        canonical = _canonical_url(absolute)

        title = _title_from_anchor(anchor)
        if not title or len(title) < 3:
            continue

        card = _find_card(anchor)
        card_text = _clean(card.get_text(" ", strip=True)) if card else _clean(anchor.get_text(" ", strip=True))

        # Hosted /jobs and /vagas always count. External links are accepted only
        # when the anchor/card actually looks like an opportunity card.
        hosted_id = _id_from_url(canonical) if _is_99jobs_host(canonical) else ""
        if not hosted_id and not _looks_like_opportunity_card(anchor, card_text):
            continue

        source_id = hosted_id or _external_source_id(canonical)
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        source_level = _employment_type(card_text)

        jobs.append(
            Job(
                source="99jobs",
                source_type="public_page",
                source_job_id=source_id,
                company=_company_from_url_or_card(canonical, card_text, title),
                title=title,
                location=_extract_location(card_text),
                url=canonical,
                description=card_text,
                employment_type=source_level,
                workplace_type=_workplace(card_text),
                metadata={
                    "discovered_from": page_url,
                    "url_style": _url_style(canonical),
                    "external_destination": not _is_99jobs_host(canonical),
                    "source_level": source_level or "",
                    "card_scope": "single_card",
                },
            )
        )

        if len(jobs) >= max_jobs:
            break

    return jobs


def _looks_like_opportunity_card(anchor, card_text: str) -> bool:
    classes = {str(x).lower() for x in (anchor.get("class") or [])}
    if "opportunity-card" in classes:
        return True

    low = card_text.lower()
    has_cta = "eu quero" in low or "ver oportunidade" in low
    has_workplace = any(
        word in low
        for word in (
            "presencial",
            "remoto",
            "remota",
            "híbrido",
            "hibrido",
            "híbrida",
            "hibrida",
        )
    )
    has_heading = anchor.find(["h1", "h2", "h3", "h4"]) is not None
    return has_heading and (has_cta or has_workplace)


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
    # Current 99jobs search results use the clickable opportunity anchor as the
    # card. Returning a large parent used to merge neighbouring jobs together.
    if _has_opportunity_card_class(anchor):
        return anchor

    current = anchor
    for _ in range(4):
        current = current.parent
        if current is None:
            break
        if _has_opportunity_card_class(current):
            return current

        if getattr(current, "name", None) in {"li", "article"}:
            job_links = [
                a for a in current.find_all("a", href=True)
                if _id_from_url(urljoin(URL, a.get("href") or ""))
                or _has_opportunity_card_class(a)
            ]
            if len(job_links) == 1:
                return current

    return anchor


def _has_opportunity_card_class(tag) -> bool:
    classes = {str(value).lower() for value in (tag.get("class") or [])}
    return "opportunity-card" in classes or any(
        "opportunity" in value and "card" in value for value in classes
    )


def _id_from_url(url: str) -> str:
    match = _JOB_PATH.search(urlsplit(url).path)
    return match.group(1) if match else ""


def _is_99jobs_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "99jobs.com" or host.endswith(".99jobs.com")


def _external_source_id(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return ""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"external-{digest}"


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)

    # URLs hospedadas na 99jobs usam o ID no path; query costuma ser tracking.
    if _is_99jobs_host(url):
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    # Em ATS externos a query pode conter o ID real da vaga. Removemos apenas
    # tracking conhecido em vez de destruir todos os parâmetros.
    clean_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in _TRACKING_QUERY_KEYS:
            continue
        clean_query.append((key, value))

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(clean_query), "")
    )


def _url_style(url: str) -> str:
    if not _is_99jobs_host(url):
        return "external"
    path = urlparse(url).path.lower()
    if "/vagas/" in path:
        return "vagas"
    if "/jobs/" in path:
        return "jobs"
    return "hosted"


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

    hosted_company = _company_from_hosted_path(url)
    if hosted_company:
        return hosted_company

    host = (urlparse(url).hostname or "").lower()
    if host and host not in {"99jobs.com", "www.99jobs.com"}:
        if host.endswith(".99jobs.com"):
            sub = host.split(".")[0]
            aliases = {
                "gruposmartfit": "Grupo Smart Fit",
                "vagasgrupodpsp": "Grupo DPSP",
                "carreiras": "99jobs",
            }
            return aliases.get(sub, sub.replace("-", " ").replace("_", " ").title())
        inferred = _company_from_external_host(host)
        if inferred:
            return inferred

    # Fallback para cards antigos que exibem a empresa em caixa alta.
    candidates = re.findall(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9 &.\-]{3,80}\b", remainder)
    ignored = {"ESTÁGIO", "TRAINEE", "PRESENCIAL", "REMOTO", "REMOTA", "HÍBRIDO", "HÍBRIDA"}
    candidates = [c for c in candidates if _clean(c).upper() not in ignored]
    if candidates:
        return _clean(candidates[-1])
    return "99jobs"



def _company_from_hosted_path(url: str) -> str:
    if not _is_99jobs_host(url):
        return ""
    host = (urlparse(url).hostname or "").lower()
    if host not in {"99jobs.com", "www.99jobs.com"}:
        return ""

    parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        marker = parts.index("jobs")
    except ValueError:
        return ""
    if marker < 1:
        return ""

    slug = parts[marker - 1].strip().lower()
    if not slug or slug in {"opportunities", "jobs", "vagas"}:
        return ""
    aliases = {
        "siemens-energy": "Siemens Energy",
        "magazine-luiza": "Magazine Luiza",
    }
    return aliases.get(slug, slug.replace("-", " ").replace("_", " ").title())

def _company_from_external_host(host: str) -> str:
    host = host.removeprefix("www.")
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2:] == ["com", "br"]:
        candidate = labels[-3]
    elif len(labels) >= 2:
        candidate = labels[-2]
    else:
        candidate = labels[0]

    generic = {"carreiras", "career", "careers", "jobs", "vagas", "talentos"}
    if candidate in generic and len(labels) >= 2:
        candidate = labels[0]
    return candidate.replace("-", " ").replace("_", " ").title()


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
