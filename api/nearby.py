from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from dataclasses import fields
from pathlib import Path
from typing import Any

from collectors.gupy_global import collect_gupy_nearby
from collectors.jobs99 import collect_99jobs_nearby
from collectors.vagas_com import collect_vagas_com
from config.sources import PUBLIC_SOURCES
from models.job import Job
from processing.classification import classify_job
from processing.deduplicate import deduplicate_jobs, fingerprint
from processing.geolocation import distance_km, enrich_job_location, is_remote, nearby_cities, resolve_location


OUTPUT_JOBS_PATH = Path("output/jobs.json")
CACHE_TTL_SECONDS = int(os.getenv("NEARBY_SEARCH_CACHE_SECONDS", "1800"))
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def search_nearby(
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    include_remote: bool = False,
    force_refresh: bool = False,
    country_code: str | None = None,
    intent: str | None = None,
) -> dict[str, Any]:
    radius_km = max(5.0, min(float(radius_km), 250.0))
    cache_key = _cache_key(latitude, longitude, radius_km, include_remote, intent)

    if not force_refresh:
        cached_response = _get_cached(cache_key)
        if cached_response is not None:
            response = dict(cached_response)
            response["cache_hit"] = True
            return response

    base_jobs = _load_base_jobs()
    base_fingerprints = {fingerprint(job) for job in base_jobs}
    cached_nearby = _filter_by_radius(
        base_jobs,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        include_remote=include_remote,
    )
    if intent:
        cached_nearby = [job for job in cached_nearby if intent in (job.detected_intents or [])]

    regional_cfg = PUBLIC_SOURCES.get("regional_search", {})
    max_cities = max(1, min(int(regional_cfg.get("max_cities", 24)), 40))
    cities = nearby_cities(
        latitude,
        longitude,
        radius_km,
        country_code=country_code,
        max_cities=max_cities,
    )

    city_names = [city["name"] for city in cities]
    collected: list[Job] = []
    source_counts: Counter[str] = Counter()
    errors: list[str] = []

    gupy_cfg = PUBLIC_SOURCES.get("gupy_global", {})
    if gupy_cfg.get("enabled", True) and city_names:
        try:
            gupy_jobs = collect_gupy_nearby(city_names, gupy_cfg, intent=intent)
            collected.extend(gupy_jobs)
            source_counts["gupy_global"] += len(gupy_jobs)
        except Exception as exc:
            errors.append(f"Gupy: {type(exc).__name__}: {exc}")

    jobs99_cfg = PUBLIC_SOURCES.get("jobs99", {})
    if regional_cfg.get("jobs99_enabled", True) and jobs99_cfg.get("enabled", True) and city_names:
        try:
            jobs99_jobs = collect_99jobs_nearby(
                city_names,
                intent=intent,
                max_cities=max(1, min(int(jobs99_cfg.get("nearby_max_cities", 6)), len(city_names))),
                max_pages_per_query=max(1, min(int(jobs99_cfg.get("nearby_max_pages_per_query", 1)), 3)),
                max_jobs=max(20, min(int(jobs99_cfg.get("nearby_max_jobs", 400)), 800)),
            )
            collected.extend(jobs99_jobs)
            source_counts["jobs99"] += len(jobs99_jobs)
        except Exception as exc:
            errors.append(f"99jobs: {type(exc).__name__}: {exc}")

    if regional_cfg.get("vagas_com_enabled", True) and city_names:
        vagas_city_limit = max(1, min(int(regional_cfg.get("vagas_com_city_limit", 4)), len(city_names)))
        max_jobs_per_query = max(10, min(int(regional_cfg.get("vagas_com_max_jobs_per_query", 40)), 80))
        regional_intent_queries = {
            "internship": ["estagio"],
            "summer_internship": [
                "estagio de ferias",
                "estagio de verao",
                "programa de ferias",
                "programa de verao",
            ],
            "seasonal_job": ["trabalho de ferias", "trabalho temporario de verao", "summer job"],
            "trainee": ["trainee"],
            "apprentice": ["jovem aprendiz"],
            "entry_level": ["junior"],
        }
        queries = regional_intent_queries.get(intent) or list(regional_cfg.get("vagas_com_queries") or [
            "estagio",
            "trainee",
            "jovem aprendiz",
            "junior",
        ])

        for city in city_names[:vagas_city_limit]:
            for query in queries:
                try:
                    jobs = collect_vagas_com(f"{query} {city}", max_jobs_per_query)
                    collected.extend(jobs)
                    source_counts["vagas_com"] += len(jobs)
                except Exception as exc:
                    errors.append(f"Vagas.com [{query} {city}]: {type(exc).__name__}: {exc}")

    collected = deduplicate_jobs(collected)
    for job in collected:
        classify_job(job)
        enrich_job_location(job)
        job.metadata["dynamic_search"] = True

    fresh_nearby = _filter_by_radius(
        collected,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        include_remote=include_remote,
    )
    if intent:
        fresh_nearby = [job for job in fresh_nearby if intent in (job.detected_intents or [])]

    combined = deduplicate_jobs(cached_nearby + fresh_nearby)
    new_jobs = [job for job in combined if fingerprint(job) not in base_fingerprints]

    response = {
        "cache_hit": False,
        "radius_km": radius_km,
        "intent": intent,
        "center": {
            "latitude": latitude,
            "longitude": longitude,
            "country_code": country_code,
        },
        "cities_searched": cities,
        "cached_jobs": len(cached_nearby),
        "newly_collected": len(new_jobs),
        "fresh_matches": len(fresh_nearby),
        "total": len(combined),
        "source_counts": dict(source_counts),
        "errors": errors[:12],
        "jobs": [job.to_dict() for job in combined],
    }

    _set_cached(cache_key, response)
    return response


def existing_nearby(
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    include_remote: bool = False,
) -> dict[str, Any]:
    radius_km = max(5.0, min(float(radius_km), 250.0))
    jobs = _filter_by_radius(
        _load_base_jobs(),
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        include_remote=include_remote,
    )
    return {
        "radius_km": radius_km,
        "total": len(jobs),
        "jobs": [job.to_dict() for job in jobs],
    }


def _filter_by_radius(
    jobs: list[Job],
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    include_remote: bool,
) -> list[Job]:
    filtered: list[Job] = []

    for job in jobs:
        job_lat = job.latitude
        job_lon = job.longitude

        if is_remote(job):
            if not include_remote:
                continue
            # "Remote" should not mean every remote vacancy in the global
            # database. Include it only when the source still ties it to a
            # city/region inside the requested radius.
            if job_lat is None or job_lon is None:
                city_hint = (job.metadata or {}).get("gupy_city") or (job.metadata or {}).get("resolved_city")
                country_hint = (job.metadata or {}).get("gupy_country") or ""
                if city_hint:
                    resolved = resolve_location(f"{city_hint}, {country_hint}".strip(", "))
                    if resolved:
                        job_lat = resolved["latitude"]
                        job_lon = resolved["longitude"]
            if job_lat is None or job_lon is None:
                continue

        if job_lat is None or job_lon is None:
            continue

        distance = distance_km(latitude, longitude, job_lat, job_lon)
        if distance <= radius_km:
            job.metadata["search_distance_km"] = round(distance, 1)
            filtered.append(job)

    return filtered


def _load_base_jobs() -> list[Job]:
    if not OUTPUT_JOBS_PATH.exists():
        return []

    try:
        raw = json.loads(OUTPUT_JOBS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(raw, list):
        return []

    allowed = {field.name for field in fields(Job)}
    jobs: list[Job] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        payload = {key: value for key, value in item.items() if key in allowed}
        try:
            jobs.append(Job(**payload))
        except TypeError:
            continue
    return jobs


def _cache_key(
    latitude: float,
    longitude: float,
    radius_km: float,
    include_remote: bool,
    intent: str | None = None,
) -> str:
    return (
        f"{latitude:.3f}:{longitude:.3f}:{radius_km:.0f}:"
        f"{int(include_remote)}:{intent or 'all'}"
    )


def _get_cached(key: str) -> dict[str, Any] | None:
    now = time.time()
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item is None:
            return None
        created_at, value = item
        if now - created_at > CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        return value


def _set_cached(key: str, response: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), response)
