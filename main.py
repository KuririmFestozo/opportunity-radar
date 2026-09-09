import os
from collections import Counter

from collectors.ashby import collect_ashby
from collectors.ciee import collect_ciee
from collectors.greenhouse import collect_greenhouse
from collectors.gupy_api import collect_gupy_api
from collectors.gupy_public import collect_gupy_public
from collectors.jobs99 import collect_99jobs
from collectors.lever import collect_lever
from collectors.search_links import build_search_links
from collectors.vagas_com import collect_vagas_com

from config.catalogs import INTENTS
from config.companies import COMPANIES
from config.profiles import PROFILES
from config.sources import PUBLIC_SOURCES, GUPY_PUBLIC_PAGES

from processing.classification import classify_job
from processing.collection_planner import build_collection_queries
from processing.deduplicate import deduplicate_jobs
from processing.export import export_all
from processing.geolocation import enrich_job_location
from processing.matching import match_job


ATS_COLLECTORS = {
    "lever": collect_lever,
    "ashby": collect_ashby,
    "greenhouse": collect_greenhouse,
}


def active_profiles():
    requested = [
        x.strip()
        for x in os.getenv(
            "ACTIVE_PROFILES",
            (
                "electrical_internship_br,"
                "electrical_summer_us,"
                "electrical_all_global,"
                "computer_science_internship_br"
            ),
        ).split(",")
        if x.strip()
    ]
    profiles = [PROFILES[x] for x in requested if x in PROFILES]
    return profiles or list(PROFILES.values())


def main():
    profiles = active_profiles()
    all_jobs = []
    source_stats = Counter()

    print("=" * 86)
    print(" OPPORTUNITY RADAR v3.3 — COLLECT FIRST, FILTER LATER")
    print("=" * 86)
    print("Perfis ativos são apenas presets de filtro; NÃO limitam a coleta.")
    print()

    # 1) ATS: always collect ALL published jobs from configured companies.
    for company in [c for c in COMPANIES if c.get("enabled", True)]:
        collector = ATS_COLLECTORS.get(company["ats"])
        if collector:
            _run(
                f'{company["name"]} [{company["ats"]}]',
                lambda c=company, fn=collector: fn(c["name"], c["slug"]),
                all_jobs,
                source_stats,
            )

    # 2) Optional official Gupy API.
    if os.getenv("GUPY_TOKEN", "").strip():
        _run("Gupy API [token]", collect_gupy_api, all_jobs, source_stats)

    # 3) Configured public Gupy company pages: collect all page jobs.
    for page in [p for p in GUPY_PUBLIC_PAGES if p.get("enabled", True)]:
        _run(
            f'{page["name"]} [gupy_public]',
            lambda p=page: collect_gupy_public(
                p["name"],
                p["base_url"],
                p.get("max_details", 30),
            ),
            all_jobs,
            source_stats,
        )

    # 4) Public job search source:
    #    IMPORTANT: query plan is global, never generated from active profiles.
    cfg = PUBLIC_SOURCES["vagas_com"]
    if cfg.get("enabled"):
        queries = build_collection_queries(
            cfg.get("max_collection_queries", 60)
        )
        print(f"\nColeta ampla Vagas.com: {len(queries)} consultas independentes dos perfis.")
        for query in queries:
            _run(
                f"Vagas.com [{query}]",
                lambda q=query: collect_vagas_com(
                    q,
                    cfg.get("max_jobs_per_query", 80),
                ),
                all_jobs,
                source_stats,
            )

    cfg = PUBLIC_SOURCES["ciee"]
    if cfg.get("enabled"):
        _run(
            "CIEE [public_page]",
            lambda: collect_ciee(cfg.get("max_jobs", 200)),
            all_jobs,
            source_stats,
        )

    cfg = PUBLIC_SOURCES["jobs99"]
    if cfg.get("enabled"):
        _run(
            "99jobs [public_page]",
            lambda: collect_99jobs(cfg.get("max_jobs", 150)),
            all_jobs,
            source_stats,
        )

    print()
    print(f"Vagas brutas: {len(all_jobs)}")

    unique = deduplicate_jobs(all_jobs)
    print(f"Vagas únicas: {len(unique)}")

    geocoded = 0
    intent_counts = Counter()

    for job in unique:
        classify_job(job)
        enrich_job_location(job)

        if job.latitude is not None and job.longitude is not None:
            geocoded += 1

        for intent_id in job.detected_intents:
            intent_counts[intent_id] += 1

    print(f"Localidades resolvidas: {geocoded}/{len(unique)}")
    print()
    print("Oportunidades detectadas por tipo:")
    for intent_id, cfg in INTENTS.items():
        print(f"  {cfg['label']:<34} {intent_counts[intent_id]:>5}")

    # Profiles now only create precomputed match scores for convenient presets.
    matches = []
    job_map = {f"{j.source}:{j.source_job_id}": j for j in unique}

    for profile in profiles:
        pmatches = [match_job(job, profile) for job in unique]
        matches.extend(pmatches)

        eligible = sorted(
            [m for m in pmatches if m.eligible],
            key=lambda m: m.score,
            reverse=True,
        )

        print()
        print(f"Preset: {profile.name} — {len(eligible)} compatíveis")
        for m in eligible[:5]:
            job = job_map[m.job_key]
            dist = (
                f" | {m.distance_km:.0f} km"
                if m.distance_km is not None
                else ""
            )
            print(
                f"  {m.score:>3}% | {job.company} | "
                f"{job.title}{dist}"
            )

    links = build_search_links(profiles)

    stats = {
        "raw_jobs": len(all_jobs),
        "unique_jobs": len(unique),
        "geocoded_jobs": geocoded,
        "profiles": [p.id for p in profiles],
        "sources": dict(source_stats),
        "intent_counts": dict(intent_counts),
    }

    export_all(unique, profiles, matches, links, stats)

    print()
    print("Dashboard gerado em output/index.html")
    print("O dashboard abre em 'Explorar tudo'.")
    print()
    print("Para usar localização atual:")
    print("  cd output")
    print("  python -m http.server 8000")
    print("  abra http://localhost:8000")


def _run(label, fn, all_jobs, source_stats):
    try:
        jobs = fn()
        all_jobs.extend(jobs)

        for job in jobs:
            source_stats[job.source] += 1

        print(f"[OK] {label:<62} {len(jobs):>4} vagas")
    except KeyboardInterrupt:
        print(f"\n[INTERROMPIDO] {label}")
        raise
    except Exception as exc:
        print(
            f"[ERRO] {label:<60} "
            f"{type(exc).__name__}: {exc}"
        )


if __name__ == "__main__":
    main()
