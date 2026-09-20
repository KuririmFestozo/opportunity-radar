from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from collectors.common import get_text
from collectors.public_early_career import (
    br_date_from_text,
    canonical_url,
    clean,
    employment_from_text,
    location_from_text,
    nearest_card,
    normalize,
    salary_from_text,
    soup,
    workplace_from_text,
)
from models.job import Job


DEFAULT_URL = "https://carreiras.iel.org.br/"
_ROUTE = re.compile(
    r"^/(?P<state>[A-Z]{2})/vaga/(?:(?P<kind>[^/]+)/)?(?P<id>\d+)(?:/(?P<slug>[^/?#]+))?/?$",
    re.IGNORECASE,
)
_CARD_LOCATION = re.compile(
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{1,80})\s*/\s*([A-Z]{2})\s+"
    r"(?:Presencial|H[ií]brido|Remoto)\b",
    re.IGNORECASE,
)


def _title_from_slug(slug: str) -> str:
    if not slug:
        return ""
    words = unquote(slug).replace("-", " ").replace("_", " ")
    return clean(words[:1].upper() + words[1:])


def _card_location(text: str) -> str:
    matches = list(_CARD_LOCATION.finditer(clean(text)))
    if not matches:
        return ""

    city, uf = matches[-1].group(1).strip(), matches[-1].group(2).upper()

    if "..." in city:
        city = city.split("...")[-1].strip()

    # Flat IEL cards may concatenate the company and city:
    # "GENESYS Manaus/AM". Strip leading ALL-CAPS company tokens only
    # when the remaining city contains normal mixed-case text.
    words = city.split()
    while (
        len(words) > 1
        and words[0].isupper()
        and any(not word.isupper() for word in words[1:])
    ):
        words.pop(0)

    cleaned_city = " ".join(words).strip()
    return f"{cleaned_city or city}, {uf}"


def _label_value(doc, label: str) -> str:
    wanted = normalize(label).rstrip(":")
    strings = [clean(value) for value in doc.stripped_strings if clean(value)]

    labels = {
        "empresa",
        "atividades",
        "requisitos",
        "cursos",
        "escolaridade",
        "cidade",
        "remuneracao",
        "beneficios",
        "horarios",
        "formato de trabalho",
    }

    for index, value in enumerate(strings):
        if normalize(value).rstrip(":") != wanted:
            continue

        for candidate in strings[index + 1:index + 8]:
            normalized = normalize(candidate).rstrip(":")
            if normalized in labels:
                break
            if candidate:
                return candidate

    return ""


def _enrich_detail(job: Job, html: str, state: str) -> Job:
    doc = soup(html)

    heading = doc.find("h1")
    if heading:
        title = clean(heading.get_text(" ", strip=True))
        if title:
            job.title = title

    company = _label_value(doc, "Empresa")
    if company:
        job.company = company

    city = _label_value(doc, "Cidade")
    if city:
        job.location = f"{city}, {state}"

    salary = _label_value(doc, "Remuneração")
    if salary:
        job.salary = salary_from_text(salary) or salary

    workplace = _label_value(doc, "Formato de trabalho")
    if workplace:
        job.workplace_type = workplace_from_text(workplace) or workplace

    activities = _label_value(doc, "Atividades")
    requirements = _label_value(doc, "Requisitos")
    description = "\n\n".join(
        value for value in (activities, requirements) if value
    )
    if description:
        job.description = description

    job.metadata["detail_fetched"] = True
    return job


def _listing_title(link, slug: str, card=None) -> str:
    root = card or link
    for node in root.find_all(["h2", "h3", "h4", "strong"], limit=6):
        value = clean(node.get_text(" ", strip=True))
        if (
            value
            and len(value) <= 140
            and "quero esta vaga" not in normalize(value)
        ):
            return value

    slug_title = _title_from_slug(slug)
    return slug_title or "Oportunidade IEL"


def _parse_listing(html: str, base_url: str, state_hint: str = ""):
    doc = soup(html)
    refs = {}

    for link in doc.find_all("a", href=True):
        href = clean(link.get("href"))
        url = canonical_url(base_url, href)
        match = _ROUTE.match(urlsplit(url).path)
        if not match:
            continue

        card = nearest_card(link)
        card_text = clean(
            card.get_text(" ", strip=True)
            if card is not None
            else link.get_text(" ", strip=True)
        )
        if (
            "quero esta vaga" not in normalize(card_text)
            and "/vaga/" not in urlsplit(url).path
        ):
            continue

        state = (match.group("state") or state_hint or "BR").upper()
        native = match.group("id")
        kind = normalize(match.group("kind") or "")
        slug = match.group("slug") or ""
        title = _listing_title(link, slug, card)

        employment = (
            "apprentice"
            if "aprendiz" in kind or "aprendiz" in normalize(card_text)
            else "internship"
            if "estagio" in kind or "estagio" in normalize(card_text)
            else employment_from_text(card_text)
        )

        job = Job(
            source="iel",
            source_job_id=f"iel:{state}:{native}",
            company="IEL / empresa anunciante",
            title=title,
            location=_card_location(card_text) or location_from_text(card_text),
            url=url,
            published_at=br_date_from_text(card_text),
            employment_type=employment,
            workplace_type=workplace_from_text(card_text),
            source_type="public_html",
            salary=salary_from_text(card_text),
            metadata={
                "platform": "iel",
                "state_scope": state,
                "native_code": native,
                "coverage": "public_listing",
            },
        )

        refs.setdefault(job.source_job_id, (job, state))

    return list(refs.values())


def collect_iel(config: dict) -> list[Job]:
    scopes = config.get("scopes") or [
        {"state": "", "url": config.get("list_url") or DEFAULT_URL}
    ]

    max_jobs = max(1, min(int(config.get("max_jobs", 2000)), 10000))
    max_details = max(0, min(int(config.get("max_details", 25)), 250))
    known = set(config.get("known_source_job_ids") or ())
    skip_known_details = bool(config.get("skip_known_details", False))

    jobs = {}
    requests = 0
    detail_requests = 0

    for scope in scopes:
        state_hint = clean(scope.get("state")).upper()
        url = scope.get("url") or (
            DEFAULT_URL.rstrip("/")
            + (f"/{state_hint}" if state_hint else "/")
        )

        listing = get_text(url)
        requests += 1

        for job, state in _parse_listing(listing, url, state_hint):
            if job.source_job_id in jobs:
                continue

            should_detail = (
                detail_requests < max_details
                and not (skip_known_details and job.source_job_id in known)
            )

            if should_detail:
                try:
                    detail_requests += 1
                    requests += 1
                    _enrich_detail(job, get_text(job.url), state)
                except Exception as exc:
                    job.metadata["detail_fetched"] = False
                    job.metadata["detail_error"] = type(exc).__name__

            jobs[job.source_job_id] = job

            if len(jobs) >= max_jobs:
                break

        if len(jobs) >= max_jobs:
            break

    out = list(jobs.values())[:max_jobs]

    if config.get("show_incremental_stats", True):
        ids = {job.source_job_id for job in out}
        print(
            f"[FAST] IEL: {len(ids & known)} conhecidos | "
            f"{len(ids - known)} novos | {requests} requests "
            f"({detail_requests} detalhes)"
        )

    return out
