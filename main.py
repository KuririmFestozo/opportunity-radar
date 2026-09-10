import os
from collections import Counter
from datetime import datetime, timezone

from collectors.ashby import collect_ashby
from collectors.ciee import collect_ciee
from collectors.corporate_ats import collect_corporate_ats
from collectors.greenhouse import collect_greenhouse
from collectors.gupy_api import collect_gupy_api
from collectors.gupy_global import collect_gupy_global
from collectors.gupy_public import collect_gupy_public
from collectors.jobs99 import collect_99jobs
from collectors.lever import collect_lever
from collectors.search_links import build_search_links
from collectors.summer_br import collect_gupy_summer_br, collect_99jobs_summer_br, collect_vagas_summer_br
from collectors.vagas_com import collect_vagas_com

from config.catalogs import INTENTS
from config.companies import COMPANIES
from config.profiles import PROFILES
from config.sources import PUBLIC_SOURCES, GUPY_PUBLIC_PAGES
from config.successfactors import SUCCESSFACTORS_PORTALS

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
                "computer_science_internship_br,"
                "summer_br"
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
    print(" OPPORTUNITY RADAR v3.13.1 — SUCCESSFACTORS CSB UNIFIED SEARCH")
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

    # 2) Public global Gupy candidate portal.
    #    This replaces company-by-company page scraping in normal operation.
    gupy_global_cfg = PUBLIC_SOURCES.get("gupy_global", {})
    if gupy_global_cfg.get("enabled", True):
        _run(
            "Gupy Global [public portal API]",
            lambda: collect_gupy_global(gupy_global_cfg),
            all_jobs,
            source_stats,
        )

    # 3) Optional authenticated Gupy API. It is account/token scoped, so it is
    #    complementary to the public global candidate portal collector.
    if os.getenv("GUPY_TOKEN", "").strip():
        _run("Gupy API [token]", collect_gupy_api, all_jobs, source_stats)

    # 4) Emergency fallback: old public company pages. Disabled by default to
    #    avoid duplicate work while Gupy Global is healthy.
    fallback_cfg = PUBLIC_SOURCES.get("gupy_public_fallback", {})
    if fallback_cfg.get("enabled"):
        for page in [p for p in GUPY_PUBLIC_PAGES if p.get("enabled", True)]:
            _run(
                f'{page["name"]} [gupy_public fallback]',
                lambda p=page: collect_gupy_public(
                    p["name"],
                    p["base_url"],
                    p.get("max_details", 30),
                ),
                all_jobs,
                source_stats,
            )

    # 5) Public corporate career portals / ATS sites. These sources catch
    #    company-owned vacancies that never reach Gupy/99jobs/Vagas.com.
    corporate_sources = [s for s in SUCCESSFACTORS_PORTALS if s.get("enabled", True)]
    if corporate_sources:
        print("\nPortais corporativos / ATS próprios.")
        for source in corporate_sources:
            _run(
                f'{source["name"]} [{source["ats"]}]',
                lambda s=source: collect_corporate_ats(s),
                all_jobs,
                source_stats,
            )

    # 6) Public Brazilian sources. Query plan is global and independent from
    #    active profiles.
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

    summer_cfg = PUBLIC_SOURCES.get("summer_br", {})
    if summer_cfg.get("enabled", True):
        print("\nBusca dedicada Brasil — férias/verão (categoria rara).")
        if summer_cfg.get("gupy_enabled", True):
            _run(
                "Gupy [Summer/Férias BR dedicado]",
                lambda: collect_gupy_summer_br({**gupy_global_cfg, **summer_cfg}),
                all_jobs,
                source_stats,
            )
        if summer_cfg.get("jobs99_enabled", True):
            _run(
                "99jobs [Summer/Férias BR dedicado]",
                lambda: collect_99jobs_summer_br(summer_cfg),
                all_jobs,
                source_stats,
            )
        if summer_cfg.get("vagas_com_enabled", True):
            _run(
                "Vagas.com [Summer/Férias BR dedicado]",
                lambda: collect_vagas_summer_br(summer_cfg),
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

    # Profiles create precomputed match scores for convenient presets only.
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
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
    print("Para abrir o dashboard com busca regional sob demanda:")
    print("  python server.py")
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
