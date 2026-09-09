import math
import re
import unicodedata
from functools import lru_cache
from typing import Optional

from models.job import Job

BR_UFS = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"
}


@lru_cache(maxsize=1)
def _city_index():
    try:
        import geonamescache
    except ImportError:
        return {}
    gc = geonamescache.GeonamesCache()
    exact = {}
    for city in gc.get_cities().values():
        key = _norm(city.get("name", ""))
        if key:
            exact.setdefault(key, []).append(city)
        for alt in city.get("alternatenames", []) or []:
            akey = _norm(alt)
            if akey:
                exact.setdefault(akey, []).append(city)
    return exact


def enrich_job_location(job: Job) -> Job:
    # Mesmo uma vaga remota pode declarar o país (ex.: "United States - Remote").
    inferred_country = infer_country(job.location)
    if inferred_country:
        job.metadata["resolved_country"] = inferred_country

    if job.latitude is not None and job.longitude is not None:
        return job
    if is_remote(job):
        return job

    resolved = resolve_location(job.location)
    if resolved:
        job.latitude = resolved["latitude"]
        job.longitude = resolved["longitude"]
        job.location_confidence = resolved["confidence"]
        job.metadata["resolved_city"] = resolved["city"]
        job.metadata["resolved_country"] = resolved["country_code"]
    return job


@lru_cache(maxsize=4096)
def resolve_location(value: str) -> Optional[dict]:
    if not value or _looks_remote(value):
        return None

    city_hint, country_hint = _location_hints(value)
    if not city_hint:
        return None

    candidates = list(_city_index().get(_norm(city_hint), []))
    if not candidates:
        shortened = re.sub(
            r"\b(metropolitan area|metro area|region|regiao|região)\b",
            "",
            city_hint,
            flags=re.I,
        ).strip()
        candidates = list(_city_index().get(_norm(shortened), []))
        city_hint = shortened or city_hint

    if not candidates:
        return None

    if country_hint:
        filtered = [c for c in candidates if c.get("countrycode") == country_hint]
        if filtered:
            candidates = filtered

    candidates.sort(key=lambda c: int(c.get("population") or 0), reverse=True)
    best = candidates[0]

    try:
        lat = float(best["latitude"])
        lon = float(best["longitude"])
    except Exception:
        return None

    return {
        "city": best.get("name") or city_hint,
        "country_code": best.get("countrycode"),
        "latitude": lat,
        "longitude": lon,
        "confidence": "city+country" if country_hint else "city",
    }


def infer_country(value: str) -> Optional[str]:
    if not value:
        return None

    raw = re.sub(r"\s+", " ", value).strip()
    normalized = _norm(raw)

    if any(x in normalized for x in ["brazil", "brasil"]):
        return "BR"
    if any(x in normalized for x in ["united states", "united states of america", "usa"]):
        return "US"

    # Reconhece padrões explícitos de UF/estado sem tentar adivinhar quando
    # a sigla existe nos dois países (ex.: AL, MA, MS, SC).
    tokens = set(re.findall(r"\b[A-Z]{2}\b", raw))
    br_unique = tokens & (BR_UFS - US_STATES)
    us_unique = tokens & (US_STATES - BR_UFS)

    if br_unique:
        return "BR"
    if us_unique:
        return "US"

    # Padrão brasileiro muito frequente: "Cidade - SP" / "Cidade - RJ".
    parts_dash = [p.strip() for p in re.split(r"\s[-–—]\s", raw) if p.strip()]
    if len(parts_dash) >= 2 and parts_dash[1].upper() in BR_UFS:
        return "BR"

    return None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_remote(job: Job) -> bool:
    values = " ".join([job.location or "", job.workplace_type or "", job.title or ""])
    return _looks_remote(values)


def _looks_remote(value: str) -> bool:
    n = _norm(value)
    return any(x in n for x in ["remote", "remoto", "remota", "home office", "work from home", "anywhere"])


def _location_hints(raw: str) -> tuple[str, Optional[str]]:
    raw = re.sub(r"\s+", " ", raw).strip()
    raw = re.split(r"\s*/\s*|\s*\|\s*|\s*;\s*", raw)[0].strip()
    parts = [p.strip() for p in re.split(r"\s[-–—]\s|,", raw) if p.strip()]
    if not parts:
        return "", None

    country = infer_country(raw)
    city = re.sub(
        r"^(location|localizacao|localização)\s*:\s*",
        "",
        parts[0],
        flags=re.I,
    ).strip()
    return city, country


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", (value or "").lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()
