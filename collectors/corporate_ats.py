"""Generic collectors for company-owned public ATS career sites.

v3.13.1 extends universal SAP SuccessFactors discovery with classic RMK tile fragments and the newer Career Site Builder Unified Search JSON API. A tenant is treated as one
public job catalogue: the collector probes the career home, /search/, discovered
/go/ pages, explicit listing URLs and the legacy public XML feed when enough
information is available. All references are merged before detail requests.
"""

from __future__ import annotations

import html as html_lib
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from collectors.common import DEFAULT_HEADERS, PUBLIC_DELAY, TIMEOUT, get_text
from models.job import Job
from processing.text import normalize


# SuccessFactors job URLs are not uniform. Common forms include:
#   /job/City-Title/1425264500/
#   /job/Title/50202-en_GB/
# Capture the numeric requisition id and tolerate a locale suffix.
_SUCCESSFACTORS_JOB_PATH = re.compile(
    r"/job/(?:[^/?#]+/)*(\d+)(?:-[A-Za-z]{2}(?:_[A-Za-z]{2})?)?(?:/|$)",
    re.IGNORECASE,
)
_EARLY_CAREER_TERMS = (
    "estagio", "estagiario", "intern", "internship", "summer", "ferias", "verao",
    "trainee", "aprendiz", "apprentice", "junior", "entry level", "graduate", "co-op", "coop",
)
_PT_MONTHS = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "marco": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9,
    "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}
_CSB_SESSION = requests.Session()
_CSB_BROWSER_HEADERS = {
    **DEFAULT_HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}
_CSB_DEFAULT_LOCALES = ("en_GB", "en_US", "pt_BR", "de_DE", "es_ES")


@dataclass
class JobRef:
    native_job_id: str
    title: str
    url: str
    location: str = ""
    discovered_from: str = ""
    discovery_methods: list[str] = field(default_factory=list)
    published_at: str | None = None


@dataclass
class DiscoveryResult:
    jobs: list[Job]
    stats: dict


def validate_successfactors_portal(config: dict) -> None:
    portal_id = str(config.get("id") or "").strip()
    name = str(config.get("name") or "").strip()
    career_url = str(config.get("career_url") or "").strip()
    listing_urls = [str(x).strip() for x in (config.get("listing_urls") or []) if str(x).strip()]
    listing_url = str(config.get("listing_url") or "").strip()
    if listing_url:
        listing_urls.append(listing_url)
    if not portal_id or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", portal_id):
        raise ValueError("SuccessFactors portal precisa de id estável em minúsculas (ex.: ternium).")
    if not name:
        raise ValueError(f"SuccessFactors portal {portal_id!r} precisa de name.")
    if not career_url and not listing_urls:
        raise ValueError(f"SuccessFactors portal {portal_id!r} precisa de career_url ou listing_urls.")


def collect_corporate_ats(config: dict) -> list[Job]:
    ats = normalize(str(config.get("ats") or "successfactors"))
    if ats == "successfactors":
        return collect_successfactors(config)
    raise ValueError(f"ATS corporativo não suportado: {config.get('ats')!r}")


def collect_successfactors(config: dict) -> list[Job]:
    """Collect one public SAP SuccessFactors tenant and return deduplicated jobs."""
    return collect_successfactors_with_stats(config).jobs


def collect_successfactors_with_stats(config: dict) -> DiscoveryResult:
    """Universal discovery for one SuccessFactors tenant.

    Discovery order is deliberately broad and source-agnostic:
      1. career home (direct job links + listing links)
      2. canonical /search/
      3. explicit and discovered /go/ pages
      4. public XML feed when it can be constructed/discovered
      5. optional keyword fallback only when broad discovery found nothing

    References from all methods are merged by native requisition id before any
    detail page is fetched.
    """
    validate_successfactors_portal(config)
    portal_id = str(config["id"]).strip()
    company = str(config["name"]).strip()

    page_size = max(10, min(int(config.get("page_size", 25)), 100))
    max_pages = max(1, min(int(config.get("max_pages_per_listing", config.get("max_pages_per_query", 200))), 300))
    max_listing_urls = max(1, min(int(config.get("max_listing_urls", 80)), 250))
    max_jobs = max(1, min(int(config.get("max_jobs", 5000)), 10000))
    max_details = max(0, min(int(config.get("max_details", 60)), 1000))
    use_xml = bool(config.get("try_xml_feed", True))
    keyword_fallback = bool(config.get("keyword_fallback", True))
    verbose = bool(config.get("show_discovery_stats", False))

    refs: dict[str, JobRef] = {}
    method_ids: dict[str, set[str]] = defaultdict(set)
    errors: list[str] = []
    pages_fetched = 0
    tile_requests = 0
    csb_json_requests = 0

    def add_refs(items: list[JobRef], method: str, origin: str = "") -> None:
        nonlocal refs
        for ref in items:
            if not ref.native_job_id:
                continue
            if origin and not ref.discovered_from:
                ref.discovered_from = origin
            methods = set(ref.discovery_methods)
            methods.add(method)
            ref.discovery_methods = sorted(methods)
            method_ids[method].add(ref.native_job_id)
            current = refs.get(ref.native_job_id)
            if current is None:
                refs[ref.native_job_id] = ref
            else:
                refs[ref.native_job_id] = _merge_refs(current, ref)

    career_url = str(config.get("career_url") or "").strip()
    explicit_urls = [str(x).strip() for x in (config.get("listing_urls") or []) if str(x or "").strip()]
    single = str(config.get("listing_url") or "").strip()
    if single:
        explicit_urls.append(single)

    home_html = ""
    discovered_listing_urls: list[str] = []
    discovered_xml_urls: list[str] = []

    if career_url:
        try:
            home_html = get_text(career_url)
            pages_fetched += 1
            add_refs(parse_successfactors_listing(home_html, career_url), "home", career_url)
            discovered_listing_urls.extend(parse_successfactors_listing_links(home_html, career_url))
            discovered_xml_urls.extend(discover_successfactors_xml_urls(home_html, career_url, config))
        except Exception as exc:
            errors.append(f"home: {type(exc).__name__}: {exc}")

    # Always probe /search/ on the same public career-site host. Career Site
    # Builder reserves the /search path and many tenants do not link it from home.
    if career_url:
        parts = urlsplit(career_url)
        root = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
        discovered_listing_urls.append(urljoin(root, "search/"))
        discovered_listing_urls.append(urljoin(root, "viewalljobs/"))

    # SuccessFactors has two important public search implementations that may
    # not render any job anchors in /search/:
    #   * classic RMK: /tile-search-results/?startrow=N (HTML fragment)
    #   * newer CSB/Unified Search: POST /services/recruiting/v1/jobs (JSON)
    # Probe both and merge the references with every other discovery route.
    csb_base = _successfactors_csb_base(config)

    if csb_base and bool(config.get("try_tile_search", False)) and len(refs) < max_jobs:
        tile_max_pages = max(1, min(int(config.get("max_tile_pages", max_pages)), max_pages, 300))
        startrow = 0
        seen_tile_signatures: set[tuple[str, ...]] = set()
        for _ in range(tile_max_pages):
            tile_url = f"{csb_base.rstrip('/')}/tile-search-results/?" + urlencode({"startrow": startrow})
            try:
                tile_html = get_text(tile_url)
                pages_fetched += 1
                tile_requests += 1
            except Exception as exc:
                errors.append(f"tile: {type(exc).__name__}: {exc}")
                break
            tile_refs = parse_successfactors_tiles(tile_html, tile_url)
            signature = tuple(sorted({ref.native_job_id for ref in tile_refs}))
            if not signature or signature in seen_tile_signatures:
                break
            seen_tile_signatures.add(signature)
            add_refs(tile_refs, "tile", tile_url)
            startrow += len(tile_refs)
            if len(refs) >= max_jobs:
                break

    if csb_base and bool(config.get("try_csb_json", False)) and len(refs) < max_jobs:
        search_html = home_html
        search_url = f"{csb_base.rstrip('/')}/search/"
        try:
            # The language switcher on /search/ advertises the locales accepted
            # by the Unified Search API. Keep this separate from the normal HTML
            # collector because some tenants return an empty job shell here.
            locale_html = get_text(search_url)
            pages_fetched += 1
            search_html = f"{search_html}\n{locale_html}"
        except Exception as exc:
            errors.append(f"csb_locales: {type(exc).__name__}: {exc}")

        locales = discover_successfactors_locales(search_html, config)
        max_csb_locales = max(1, min(int(config.get("max_csb_locales", 16)), 32))
        csb_pages = max(1, min(int(config.get("max_csb_pages_per_locale", max_pages)), max_pages, 200))
        jobs_api = f"{csb_base.rstrip('/')}/services/recruiting/v1/jobs"

        for locale in locales[:max_csb_locales]:
            for page_number in range(csb_pages):
                try:
                    payload = _post_successfactors_json(
                        jobs_api,
                        {
                            "keywords": "",
                            "locale": locale,
                            "location": "",
                            "pageNumber": page_number,
                            "sortBy": "recent",
                        },
                    )
                    pages_fetched += 1
                    csb_json_requests += 1
                except Exception as exc:
                    errors.append(f"csb_json[{locale}]: {type(exc).__name__}: {exc}")
                    break

                csb_refs, total_jobs = parse_successfactors_csb_json(payload, csb_base, locale)
                if not csb_refs:
                    break
                add_refs(csb_refs, "csb_json", jobs_api)

                if len(refs) >= max_jobs:
                    break
                if total_jobs and (page_number + 1) * 10 >= total_jobs:
                    break
                if len(csb_refs) < 10:
                    break
            if len(refs) >= max_jobs:
                break

    queue: deque[tuple[str, str]] = deque()
    queued: set[str] = set()

    def enqueue(url: str, method: str) -> None:
        canonical = _canonical_listing_url(url)
        if not canonical or canonical in queued or len(queued) >= max_listing_urls:
            return
        path = urlsplit(canonical).path.lower()
        if "/job/" in path:
            return
        queued.add(canonical)
        queue.append((canonical, method))

    for url in explicit_urls:
        enqueue(url, "explicit")
    for url in discovered_listing_urls:
        method = "search" if "/search/" in urlsplit(url).path.lower() else "go"
        enqueue(url, method)

    # If the career home itself is effectively a listing, keep it in the graph.
    if career_url and not queue:
        enqueue(career_url, "home_listing")

    while queue and len(refs) < max_jobs:
        listing_url, method = queue.popleft()
        seen_page_signatures: set[tuple[str, ...]] = set()
        for page in range(max_pages):
            page_url = _successfactors_listing_url(
                listing_url,
                query="",
                startrow=page * page_size,
            )
            try:
                html = get_text(page_url)
                pages_fetched += 1
            except Exception as exc:
                errors.append(f"{method}: {type(exc).__name__}: {exc}")
                break

            page_refs = parse_successfactors_listing(html, page_url)
            signature = tuple(sorted({ref.native_job_id for ref in page_refs}))
            if not signature or signature in seen_page_signatures:
                break
            seen_page_signatures.add(signature)
            add_refs(page_refs, method, page_url)

            # Listing pages frequently expose other /go/ categories. Add them to
            # the same discovery graph; duplicates are harmless.
            for child in parse_successfactors_listing_links(html, page_url):
                child_method = "search" if "/search/" in urlsplit(child).path.lower() else "go"
                enqueue(child, child_method)
            discovered_xml_urls.extend(discover_successfactors_xml_urls(html, page_url, config))

            if len(refs) >= max_jobs:
                break
            # A short page usually means the end. Some tenants repeat the last
            # page instead; the signature guard above handles that case.
            if len(page_refs) < page_size:
                break

    if use_xml and len(refs) < max_jobs:
        xml_urls = []
        seen_xml = set()
        for url in list(config.get("xml_feed_urls") or []) + discovered_xml_urls:
            value = str(url or "").strip()
            if value and value not in seen_xml:
                seen_xml.add(value)
                xml_urls.append(value)
        for xml_url in xml_urls:
            try:
                xml_text = get_text(xml_url)
                pages_fetched += 1
                xml_refs = parse_successfactors_xml(xml_text, xml_url)
                add_refs(xml_refs, "xml", xml_url)
            except Exception as exc:
                errors.append(f"xml: {type(exc).__name__}: {exc}")
            if len(refs) >= max_jobs:
                break

    # Keyword searches are only a recovery path for tenants where the public
    # broad catalogue cannot be parsed. They are not the primary collection mode.
    if not refs and keyword_fallback:
        fallback_terms = list(config.get("queries") or [
            "intern", "estagio", "summer", "trainee", "apprentice", "junior", "engineering", "software",
        ])
        fallback_urls = list(queued) or explicit_urls
        if career_url:
            parts = urlsplit(career_url)
            fallback_urls.append(urlunsplit((parts.scheme, parts.netloc, "/search/", "", "")))
        seen_fallback_urls = set()
        for listing_url in fallback_urls:
            canonical = _canonical_listing_url(listing_url)
            if not canonical or canonical in seen_fallback_urls:
                continue
            seen_fallback_urls.add(canonical)
            for term in fallback_terms:
                try:
                    html = get_text(_successfactors_listing_url(canonical, query=term, startrow=0))
                    pages_fetched += 1
                    add_refs(parse_successfactors_listing(html, canonical), "keyword", canonical)
                except Exception as exc:
                    errors.append(f"keyword: {type(exc).__name__}: {exc}")
                if len(refs) >= max_jobs:
                    break
            if refs or len(refs) >= max_jobs:
                break

    ordered = sorted(refs.values(), key=lambda ref: (not _is_priority_ref(ref), ref.title.lower()))[:max_jobs]
    detail_ids = _select_detail_ids(ordered, max_details)

    jobs: list[Job] = []
    detail_requests = 0
    for ref in ordered:
        job = _job_from_ref(ref, portal_id, company)
        if ref.native_job_id in detail_ids:
            detail_requests += 1
            try:
                detail_html = get_text(ref.url)
                detail = parse_successfactors_detail(
                    detail_html,
                    ref.url,
                    portal_id=portal_id,
                    company=company,
                    fallback_title=ref.title,
                    fallback_location=ref.location,
                )
                if detail:
                    job = detail
                    job.metadata["discovered_from"] = ref.discovered_from
                    job.metadata["discovery_methods"] = sorted(set(ref.discovery_methods))
            except Exception:
                job.metadata["detail_fetched"] = False
        jobs.append(job)

    stats = {
        "portal_id": portal_id,
        "company": company,
        "method_counts": {method: len(ids) for method, ids in sorted(method_ids.items())},
        "references_seen": sum(len(ids) for ids in method_ids.values()),
        "unique_refs": len(refs),
        "jobs_returned": len(jobs),
        "listing_pages_fetched": pages_fetched,
        "tile_requests": tile_requests,
        "csb_json_requests": csb_json_requests,
        "detail_requests": detail_requests,
        "errors": errors,
    }

    if verbose:
        _print_discovery_stats(stats)

    return DiscoveryResult(jobs=jobs, stats=stats)


def discover_successfactors_listing_urls(career_url: str) -> list[str]:
    if not career_url:
        return []
    try:
        html = get_text(career_url)
    except Exception:
        return []
    return parse_successfactors_listing_links(html, career_url)


def _successfactors_csb_base(config: dict) -> str:
    """Return the public CSB/RMK base, preserving an optional brand prefix."""
    candidates = [
        str(config.get("career_url") or "").strip(),
        *[str(x or "").strip() for x in (config.get("listing_urls") or [])],
        str(config.get("listing_url") or "").strip(),
    ]
    for raw in candidates:
        if not raw:
            continue
        parts = urlsplit(raw)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            continue
        path = parts.path or "/"
        # Strip a known endpoint while preserving any multi-brand path prefix.
        path = re.sub(
            r"/(?:search|viewalljobs|tile-search-results|services/recruiting/v1/jobs)/?$",
            "",
            path,
            flags=re.IGNORECASE,
        )
        path = re.sub(r"/(?:go|job)/.*$", "", path, flags=re.IGNORECASE)
        path = re.sub(r"/career/?$", "", path, flags=re.IGNORECASE)
        path = path.rstrip("/")
        return f"{parts.scheme}://{parts.netloc}{path}"
    return ""


def discover_successfactors_locales(html: str, config: dict | None = None) -> list[str]:
    """Return supported CSB locales in a stable, useful order."""
    config = config or {}
    found: list[str] = []
    seen: set[str] = set()

    def add(locale: str) -> None:
        value = str(locale or "").strip()
        if not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", value):
            return
        if value not in seen:
            seen.add(value)
            found.append(value)

    for locale in config.get("csb_locales") or []:
        add(str(locale))
    for match in re.finditer(r"(?:[?&]|&amp;)locale=([a-z]{2}_[A-Z]{2})\b", html or ""):
        add(match.group(1))
    for match in re.finditer(r"/(?:\d+)-([a-z]{2}_[A-Z]{2})/?(?:[?'\"#<]|$)", html or ""):
        add(match.group(1))
    for locale in _CSB_DEFAULT_LOCALES:
        add(locale)

    priority = {locale: i for i, locale in enumerate(_CSB_DEFAULT_LOCALES)}
    configured = [str(x) for x in (config.get("csb_locales") or [])]
    configured_priority = {locale: i for i, locale in enumerate(configured)}
    return sorted(
        found,
        key=lambda loc: (
            0 if loc in configured_priority else 1,
            configured_priority.get(loc, 999),
            priority.get(loc, 999),
            loc,
        ),
    )


def parse_successfactors_tiles(html: str, page_url: str) -> list[JobRef]:
    """Parse classic RMK /tile-search-results/ fragments."""
    soup = BeautifulSoup(html or "", "html.parser")
    found: dict[str, JobRef] = {}
    tiles = soup.select("li.job-tile, li[class*='job-id-']")
    for tile in tiles:
        classes = " ".join(tile.get("class") or [])
        class_match = re.search(r"\bjob-id-(\d+)\b", classes)
        raw_path = str(tile.get("data-url") or "").strip()
        link = tile.select_one("a.jobTitle-link") or tile.find("a", href=True)
        if not raw_path and link is not None:
            raw_path = str(link.get("href") or "").strip()
        if not raw_path:
            continue
        absolute = _canonical_job_url(urljoin(page_url, html_lib.unescape(raw_path)))
        native_id = class_match.group(1) if class_match else _successfactors_native_id(absolute)
        if not native_id:
            continue
        title = _clean(link.get_text(" ", strip=True)) if link is not None else ""
        if not title:
            continue
        city = ""
        city_node = tile.select_one("[id$='-section-city-value'], .jobLocation, .job-location")
        if city_node is not None:
            city = _clean(city_node.get_text(" ", strip=True))
        ref = JobRef(
            native_job_id=native_id,
            title=title,
            url=absolute,
            location=city,
            discovered_from=page_url,
            discovery_methods=["tile"],
        )
        current = found.get(native_id)
        found[native_id] = ref if current is None else _merge_refs(current, ref)
    return list(found.values())


def parse_successfactors_csb_json(payload: dict, base_url: str, locale: str) -> tuple[list[JobRef], int]:
    """Parse the newer Career Site Builder Unified Search JSON response."""
    records = payload.get("jobSearchResult") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return [], 0
    found: dict[str, JobRef] = {}
    for item in records:
        response = item.get("response") if isinstance(item, dict) else None
        if not isinstance(response, dict):
            continue
        raw_id = response.get("id")
        native_id = re.match(r"\d+", str(raw_id or ""))
        if not native_id:
            continue
        native_id = native_id.group(0)
        title = _clean(str(response.get("unifiedStandardTitle") or response.get("jobTitle") or response.get("title") or ""))
        if not title:
            continue
        raw_slug = html_lib.unescape(str(response.get("unifiedUrlTitle") or response.get("urlTitle") or "job"))
        slug = re.sub(r"[?#&]+", "-", raw_slug.strip("/")) or "job"
        slug = re.sub(r"-{2,}", "-", slug)
        url = f"{base_url.rstrip('/')}/job/{slug}/{native_id}-{locale}/"

        locations = response.get("jobLocationShort") or response.get("jobLocation") or []
        if not isinstance(locations, list):
            locations = [locations]
        clean_locations: list[str] = []
        for value in locations:
            text = BeautifulSoup(html_lib.unescape(str(value or "")), "html.parser").get_text(" ", strip=True)
            text = _clean(text)
            if text and text not in clean_locations:
                clean_locations.append(text)

        posted_raw = response.get("unifiedStandardStart") or response.get("datePosted") or response.get("postedDate")
        ref = JobRef(
            native_job_id=native_id,
            title=title,
            url=_canonical_job_url(url),
            location=" / ".join(clean_locations),
            discovered_from=f"{base_url.rstrip('/')}/services/recruiting/v1/jobs",
            discovery_methods=["csb_json"],
            published_at=_parse_csb_date(str(posted_raw or "")),
        )
        current = found.get(native_id)
        found[native_id] = ref if current is None else _merge_refs(current, ref)
    try:
        total = int(payload.get("totalJobs") or 0)
    except (TypeError, ValueError):
        total = 0
    return list(found.values()), total


def _parse_csb_date(value: str) -> str | None:
    value = _clean(value)
    if not value:
        return None
    patterns = (
        (r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", "mdy"),
        (r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$", "dmy"),
    )
    for pattern, order in patterns:
        match = re.fullmatch(pattern, value)
        if not match:
            continue
        a, b, year = map(int, match.groups())
        if year < 100:
            year += 2000
        month, day = (a, b) if order == "mdy" else (b, a)
        try:
            return datetime(year, month, day, tzinfo=timezone.utc).isoformat()
        except ValueError:
            return None
    return _parse_date(value)


def _post_successfactors_json(url: str, payload: dict) -> dict:
    """POST to the public zero-auth CSB job search API with light retry handling."""
    if PUBLIC_DELAY > 0:
        time.sleep(PUBLIC_DELAY)
    headers = dict(_CSB_BROWSER_HEADERS)
    headers["Content-Type"] = "application/json"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = _CSB_SESSION.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(0.8 * (2 ** attempt))
                continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("CSB jobs API não retornou um objeto JSON")
            return data
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt >= 2:
                raise
            time.sleep(0.5 * (2 ** attempt))
    if last_error:
        raise last_error
    raise RuntimeError("Falha inesperada no CSB jobs API")


def parse_successfactors_listing_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        absolute = _canonical_listing_url(urljoin(page_url, anchor.get("href") or ""))
        path = urlsplit(absolute).path.lower()
        if "/go/" not in path and "/search/" not in path and "/viewalljobs/" not in path:
            continue
        if absolute not in seen:
            seen.add(absolute)
            found.append(absolute)
    return found


def parse_successfactors_listing(html: str, page_url: str) -> list[JobRef]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, JobRef] = {}
    for anchor in soup.find_all("a", href=True):
        absolute = _canonical_job_url(urljoin(page_url, (anchor.get("href") or "").strip()))
        native_id = _successfactors_native_id(absolute)
        if not native_id:
            continue
        title = _clean(anchor.get_text(" ", strip=True)) or _title_from_parent(anchor)
        if len(title) < 3:
            continue
        card = _nearest_job_container(anchor)
        card_text = _clean(card.get_text("\n", strip=True)) if card else title
        ref = JobRef(
            native_job_id=native_id,
            title=title,
            url=absolute,
            location=_extract_location(card_text),
            discovered_from=page_url,
        )
        current = found.get(native_id)
        found[native_id] = ref if current is None else _merge_refs(current, ref)
    return list(found.values())


def discover_successfactors_xml_urls(html: str, page_url: str, config: dict | None = None) -> list[str]:
    """Discover or construct public XML feed URLs when enough data is visible."""
    config = config or {}
    urls: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = _clean(value)
        if value and value not in seen:
            seen.add(value)
            urls.append(value)

    for value in config.get("xml_feed_urls") or []:
        add(str(value))

    company_ids = set()
    configured_id = str(config.get("company_id") or "").strip()
    if configured_id:
        company_ids.add(configured_id)

    for candidate in (page_url,):
        qs = parse_qs(urlsplit(candidate).query)
        for value in qs.get("company", []):
            if value:
                company_ids.add(value)

    for match in re.finditer(r"(?:[?&]|&amp;)company=([A-Za-z0-9_.-]+)", html or "", re.IGNORECASE):
        company_ids.add(match.group(1))
    for match in re.finditer(r"[\"']company(?:Id)?[\"']\s*[:=]\s*[\"']([A-Za-z0-9_.-]+)[\"']", html or "", re.IGNORECASE):
        company_ids.add(match.group(1))

    feed_hosts = set()
    page_parts = urlsplit(page_url)
    if "successfactors." in page_parts.netloc.lower() or "sapcloud." in page_parts.netloc.lower():
        feed_hosts.add(f"{page_parts.scheme}://{page_parts.netloc}")

    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(page_url, anchor.get("href") or "")
        parts = urlsplit(absolute)
        if "successfactors." in parts.netloc.lower() or "sapcloud." in parts.netloc.lower():
            feed_hosts.add(f"{parts.scheme}://{parts.netloc}")
            qs = parse_qs(parts.query)
            for value in qs.get("company", []):
                if value:
                    company_ids.add(value)

    for host in sorted(feed_hosts):
        for company_id in sorted(company_ids):
            add(
                f"{host}/career?" + urlencode({
                    "company": company_id,
                    "career_ns": "job_listing_summary",
                    "resultType": "XML",
                })
            )
    return urls


def parse_successfactors_xml(xml_text: str, feed_url: str) -> list[JobRef]:
    """Parse the public RCM XML feed with tolerant field-name matching."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    aliases = {
        "id": {"id", "jobid", "jobreqid", "job_req_id", "requisitionid", "reqid"},
        "title": {"title", "jobtitle", "job_title", "positiontitle"},
        "url": {"url", "joburl", "job_url", "applyurl", "externalurl"},
        "location": {"location", "joblocation", "job_location", "city", "locationname"},
    }
    jobs: dict[str, JobRef] = {}

    for node in root.iter():
        children = list(node)
        if len(children) < 2:
            continue
        values: dict[str, str] = {}
        for child in children:
            tag = _xml_local_name(child.tag)
            text = _clean(" ".join(child.itertext()))
            if not text:
                continue
            for key, names in aliases.items():
                if tag in names and key not in values:
                    values[key] = text
        url = values.get("url", "")
        native_id = values.get("id", "") or _successfactors_native_id(url)
        title = values.get("title", "")
        if not native_id or not title:
            continue
        if url:
            url = _canonical_job_url(urljoin(feed_url, url))
        ref = JobRef(
            native_job_id=re.sub(r"\D.*$", "", native_id) or native_id,
            title=title,
            url=url,
            location=values.get("location", ""),
            discovered_from=feed_url,
            discovery_methods=["xml"],
        )
        if not ref.url:
            continue
        current = jobs.get(ref.native_job_id)
        jobs[ref.native_job_id] = ref if current is None else _merge_refs(current, ref)
    return list(jobs.values())


def parse_successfactors_detail(
    html: str,
    page_url: str,
    *,
    portal_id: str,
    company: str,
    fallback_title: str = "",
    fallback_location: str = "",
) -> Job | None:
    soup = BeautifulSoup(html, "html.parser")
    native_id = _successfactors_native_id(page_url)
    if not native_id:
        return None
    title = _detail_title(soup) or fallback_title
    if not title:
        return None
    page_text = soup.get_text("\n", strip=True)
    location = _extract_detail_field(page_text, ("Localização", "Localizacao", "Location", "Job Location")) or fallback_location
    description = _detail_description(soup)
    return Job(
        source="successfactors",
        source_type="public_career_site",
        source_job_id=_namespaced_job_id(portal_id, native_id),
        company=company,
        title=title,
        location=location,
        url=_canonical_job_url(page_url),
        description=description,
        published_at=_extract_published_at(page_text),
        metadata={
            "ats": "successfactors",
            "portal_id": portal_id,
            "native_job_id": native_id,
            "corporate_source": company,
            "detail_fetched": True,
        },
    )


def _resolve_listing_urls(config: dict) -> list[str]:
    """Compatibility helper retained for v3.11/v3.12 callers/tests."""
    explicit = [str(x).strip() for x in (config.get("listing_urls") or []) if str(x or "").strip()]
    single = str(config.get("listing_url") or "").strip()
    if single:
        explicit.append(single)
    career_url = str(config.get("career_url") or "").strip()
    discovered = discover_successfactors_listing_urls(career_url) if career_url else []
    if career_url:
        parts = urlsplit(career_url)
        root = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
        discovered.append(urljoin(root, "search/"))
    urls: list[str] = []
    seen: set[str] = set()
    for value in explicit + discovered:
        canonical = _canonical_listing_url(value)
        if canonical and canonical not in seen:
            seen.add(canonical)
            urls.append(canonical)
    if not urls and career_url:
        urls.append(_canonical_listing_url(career_url))
    return urls


def _select_detail_ids(refs: list[JobRef], max_details: int) -> set[str]:
    if max_details <= 0:
        return set()
    selected: list[str] = []
    for ref in refs:
        if _is_priority_ref(ref) and ref.native_job_id not in selected:
            selected.append(ref.native_job_id)
            if len(selected) >= max_details:
                return set(selected)
    for ref in refs:
        if ref.native_job_id not in selected:
            selected.append(ref.native_job_id)
            if len(selected) >= max_details:
                break
    return set(selected)


def _job_from_ref(ref: JobRef, portal_id: str, company: str) -> Job:
    return Job(
        source="successfactors",
        source_type="public_career_site",
        source_job_id=_namespaced_job_id(portal_id, ref.native_job_id),
        company=company,
        title=ref.title,
        location=ref.location,
        url=ref.url,
        description="",
        published_at=ref.published_at,
        metadata={
            "ats": "successfactors",
            "portal_id": portal_id,
            "native_job_id": ref.native_job_id,
            "corporate_source": company,
            "discovered_from": ref.discovered_from,
            "discovery_methods": sorted(set(ref.discovery_methods)),
            "detail_fetched": False,
        },
    )


def _merge_refs(a: JobRef, b: JobRef) -> JobRef:
    best = b if _ref_quality(b) > _ref_quality(a) else a
    other = a if best is b else b
    methods = sorted(set(a.discovery_methods) | set(b.discovery_methods))
    return JobRef(
        native_job_id=best.native_job_id,
        title=best.title or other.title,
        url=best.url or other.url,
        location=best.location or other.location,
        discovered_from=best.discovered_from or other.discovered_from,
        discovery_methods=methods,
        published_at=best.published_at or other.published_at,
    )


def _successfactors_listing_url(base_url: str, *, query: str = "", startrow: int = 0) -> str:
    parts = urlsplit(base_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["q"] = query
    params.setdefault("sortColumn", "referencedate")
    params.setdefault("sortDirection", "desc")
    if startrow > 0:
        params["startrow"] = str(startrow)
    else:
        params.pop("startrow", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


def _successfactors_native_id(url: str) -> str:
    match = _SUCCESSFACTORS_JOB_PATH.search(urlsplit(url).path)
    return match.group(1) if match else ""


def _namespaced_job_id(portal_id: str, native_id: str) -> str:
    return f"{portal_id}:{native_id}"


def _canonical_job_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _canonical_listing_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _title_from_parent(anchor) -> str:
    parent = anchor.parent
    for _ in range(4):
        if parent is None:
            break
        heading = parent.find(["h1", "h2", "h3", "h4"])
        if heading:
            value = _clean(heading.get_text(" ", strip=True))
            if value:
                return value
        parent = parent.parent
    return ""


def _nearest_job_container(anchor):
    for parent in anchor.parents:
        if getattr(parent, "name", None) in {"li", "article", "tr"}:
            return parent
        classes = " ".join(parent.get("class", [])) if hasattr(parent, "get") else ""
        if re.search(r"job|career|results?", classes, re.IGNORECASE):
            text = _clean(parent.get_text(" ", strip=True))
            if 10 < len(text) < 2500:
                return parent
    return anchor.parent


def _extract_location(text: str) -> str:
    text = _clean(text.replace("\n", " "))
    patterns = (
        r"(?:Localização|Localizacao|Location|Job Location)\s*[:\-]?\s*(.{2,100}?)(?=\s+(?:País|Pais|Country|Req\.?\s*(?:No\.?|ID)|Título|Titulo|Title|Employment Type|$))",
        r"(?:Localização|Localizacao|Location|Job Location)\s*[:\-]?\s*([A-Za-zÀ-ÿ .,'\-/]{2,100})$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = _clean(match.group(1))
            if value:
                return value
    return ""


def _extract_detail_field(page_text: str, labels: tuple[str, ...]) -> str:
    lines = [_clean(line) for line in page_text.splitlines() if _clean(line)]
    label_norms = {normalize(label) for label in labels}
    for index, line in enumerate(lines):
        norm = normalize(line.rstrip(":"))
        if norm in label_norms and index + 1 < len(lines):
            return lines[index + 1]
        for label in labels:
            match = re.match(rf"^{re.escape(label)}\s*:\s*(.+)$", line, re.IGNORECASE)
            if match:
                return _clean(match.group(1))
    return ""


def _detail_title(soup: BeautifulSoup) -> str:
    for selector in ("h1", "meta[property='og:title']", "meta[name='twitter:title']"):
        element = soup.select_one(selector)
        if not element:
            continue
        value = element.get("content") if element.name == "meta" else element.get_text(" ", strip=True)
        value = _clean(value or "")
        if value and normalize(value) not in {"nossas oportunidades", "our opportunities", "career site"}:
            return value
    return ""


def _detail_description(soup: BeautifulSoup) -> str:
    selectors = (
        "[itemprop='description']", ".jobdescription", ".jobDescriptionContent",
        ".job-description", "#job-description", ".jobDesc",
    )
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            value = _clean_multiline(element.get_text("\n", strip=True))
            if len(value) >= 40:
                return value
    for element in soup.find_all(["div", "section"], class_=re.compile(r"description|jobdesc", re.IGNORECASE)):
        value = _clean_multiline(element.get_text("\n", strip=True))
        if len(value) >= 40:
            return value
    main = soup.find("main") or soup.find("article")
    if main:
        return _clean_multiline(main.get_text("\n", strip=True))
    return ""


def _extract_published_at(page_text: str) -> str | None:
    lines = [_clean(line) for line in page_text.splitlines() if _clean(line)]
    candidates: list[str] = []
    for i, line in enumerate(lines):
        if normalize(line.rstrip(":")) in {"data", "date", "posting date", "data de publicacao"} and i + 1 < len(lines):
            candidates.append(lines[i + 1])
        match = re.search(r"(?:Data|Date|Posting Date)\s*:\s*(.+)$", line, re.IGNORECASE)
        if match:
            candidates.append(_clean(match.group(1)))
    for value in candidates:
        parsed = _parse_date(value)
        if parsed:
            return parsed
    return None


def _parse_date(value: str) -> str | None:
    value = normalize(value).replace(" de ", " ")
    match = re.fullmatch(r"(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})", value)
    if match:
        day = int(match.group(1)); month = _PT_MONTHS.get(match.group(2).rstrip(".")); year = int(match.group(3))
        if month:
            try:
                return datetime(year, month, day, tzinfo=timezone.utc).isoformat()
            except ValueError:
                return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def _is_priority_ref(ref: JobRef) -> bool:
    title = f" {normalize(ref.title)} "
    return any(f" {normalize(term)} " in title for term in _EARLY_CAREER_TERMS)


def _ref_quality(ref: JobRef) -> int:
    return (
        int(bool(ref.title)) * 3
        + int(bool(ref.location)) * 2
        + int(bool(ref.url))
        + int(bool(ref.published_at))
        + min(len(ref.title), 100) // 50
    )


def _xml_local_name(tag: str) -> str:
    return normalize(str(tag).split("}")[-1]).replace("-", "").replace("_", "")


def _print_discovery_stats(stats: dict) -> None:
    print(f"  {stats['company']} [SuccessFactors universal]")
    for method, count in stats.get("method_counts", {}).items():
        print(f"    {method:<12} {count:>5} refs")
    print(f"    {'somadas':<12} {stats.get('references_seen', 0):>5} refs")
    print(f"    {'únicas':<12} {stats.get('unique_refs', 0):>5} refs")
    print(f"    {'tiles req':<12} {stats.get('tile_requests', 0):>5}")
    print(f"    {'CSB JSON':<12} {stats.get('csb_json_requests', 0):>5}")
    print(f"    {'detalhes':<12} {stats.get('detail_requests', 0):>5}")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_multiline(value: str) -> str:
    lines = [_clean(line) for line in (value or "").splitlines()]
    return "\n".join(line for line in lines if line)
