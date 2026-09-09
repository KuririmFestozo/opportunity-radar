from urllib.parse import urlencode

from models.profile import SearchProfile
from processing.search_planner import build_linkedin_queries


BRAZIL_WIDE_SEARCHES = [
    "estágio",
    "estágio de verão",
    "estágio de férias",
    "programa de estágio de férias",
    "summer internship",
    "summer job",
    "trainee",
    "jovem aprendiz",
    "iniciação científica",
]


def build_search_links(profiles: list[SearchProfile]) -> list[dict]:
    links = []

    for profile in profiles:
        for query, location in build_linkedin_queries(profile):
            links.append({
                "profile_id": profile.id,
                "provider": "LinkedIn",
                "query": query,
                "kind": "manual_search_link",
                "url": _linkedin(query, location),
                "notes": "Busca manual; sem scraping automatizado.",
            })

        # Generic Brazilian summer/vacation searches are useful even when
        # the profile course is very specific.
        for query in BRAZIL_WIDE_SEARCHES:
            links.append({
                "profile_id": profile.id,
                "provider": "Indeed",
                "query": f"{query} — Brasil",
                "kind": "manual_search_link",
                "url": _indeed(query),
                "notes": "Busca externa complementar.",
            })

    return _dedupe(links)


def _linkedin(keywords: str, location: str) -> str:
    params = {
        "keywords": keywords,
        "location": location,
        "f_TPR": "r604800",
    }
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


def _indeed(query: str) -> str:
    return "https://br.indeed.com/jobs?" + urlencode({"q": query, "fromage": "14"})


def _dedupe(items):
    seen = set()
    out = []
    for item in items:
        key = (item["profile_id"], item["provider"], item["url"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
