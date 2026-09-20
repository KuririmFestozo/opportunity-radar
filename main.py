import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from collectors.ashby import collect_ashby
from collectors.ciee import collect_ciee
from collectors.corporate_ats import collect_corporate_ats
from collectors.greenhouse import collect_greenhouse
from collectors.gupy_api import collect_gupy_api
from collectors.gupy_global import collect_gupy_global
from collectors.gupy_public import collect_gupy_public
from collectors.jobs99 import collect_99jobs
from collectors.lever import collect_lever
from collectors.inhire import collect_inhire
from collectors.izirh import collect_izirh
from collectors.smartrecruiters import collect_smartrecruiters
from collectors.workday import collect_workday
from collectors.totvs import collect_totvs
from collectors.eightfold import collect_eightfold
from config.eightfold import EIGHTFOLD_TENANTS
from collectors.teamtailor import collect_teamtailor
from collectors.search_links import build_search_links
from collectors.summer_br import collect_gupy_summer_br, collect_99jobs_summer_br, collect_vagas_summer_br
from collectors.successfactors_incremental import probe_successfactors_recent
from collectors.vagas_com import collect_vagas_com
from collectors.early_career_brazil import collect_early_career_source

from config.catalogs import INTENTS
from config.companies import COMPANIES
from config.profiles import PROFILES
from config.additional_ats import (
    TOTVS_TENANTS,
    TEAMTAILOR_BOARDS,
    INHIRE_TENANTS,
    IZIRH_TENANTS,
    SMARTRECRUITERS_BOARDS,
    WORKDAY_BOARDS,
)
from config.sources import PUBLIC_SOURCES, GUPY_PUBLIC_PAGES
from config.successfactors import SUCCESSFACTORS_PORTALS
from config.early_career_sources import EARLY_CAREER_SOURCES

from processing.classification import classify_job
from processing.collection_planner import build_collection_queries
from processing.deduplicate import deduplicate_jobs
from processing.export import export_all
from processing.geolocation import enrich_job_location
from processing.matching import match_job
from storage.job_store import JobStore, deduplicate_source_jobs


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


def additional_ats_runtime(source, source_name, store, full_refresh):
    runtime = dict(source)
    runtime["known_source_job_ids"] = (
        set() if full_refresh else store.known_ids(source_name, prefix=f"{source['id']}:")
    )
    runtime["early_stop_known_pages"] = 0 if full_refresh else 2
    runtime["skip_known_details"] = not full_refresh
    runtime["show_incremental_stats"] = True
    return runtime


def main():
    profiles = active_profiles()
    all_jobs = []
    source_stats = Counter()
    store = JobStore()
    bootstrap = store.bootstrap_from_json(Path("output/jobs.json"))
    full_refresh = os.getenv("FULL_REFRESH", "").strip().lower() in {"1", "true", "yes", "on"}
    full_discovery = os.getenv("FULL_DISCOVERY", "").strip().lower() in {"1", "true", "yes", "on"}

    print("=" * 86)
    print(" OPPORTUNITY RADAR v3.15.3 — STRICT INTENTS + SAP EXPANSION")
    print("=" * 86)
    print("Perfis ativos são apenas presets de filtro; NÃO limitam a coleta.")
    if bootstrap["imported"]:
        print(f"Banco incremental criado do jobs.json: {bootstrap['imported']} vagas preservadas.")
    else:
        print(f"Banco incremental: {store.count()} registros armazenados.")
    if full_refresh:
        print("Modo FULL_REFRESH: early-stop e cache de detalhes desativados nesta execução.")
    else:
        print("Modo incremental: early-stop ativo para fontes paginadas com IDs conhecidos.")
    if full_discovery:
        print("Modo FULL_DISCOVERY: baseline exaustivo; FAST-stop SAP e query early-stop desativados.")
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

    # Regional sources first; known IDs are isolated by source and tenant.
    for source_name, registry, collector in (
        ("eightfold", EIGHTFOLD_TENANTS, collect_eightfold),
        ("totvs", TOTVS_TENANTS, collect_totvs),
        ("teamtailor", TEAMTAILOR_BOARDS, collect_teamtailor),
        ("smartrecruiters", SMARTRECRUITERS_BOARDS, collect_smartrecruiters),
        ("inhire", INHIRE_TENANTS, collect_inhire),
        ("izirh", IZIRH_TENANTS, collect_izirh),
        ("workday", WORKDAY_BOARDS, collect_workday),
    ):
        for source in registry:
            if not source.get("enabled", True):
                continue
            runtime = additional_ats_runtime(source, source_name, store, full_refresh)
            _run(f'{source["name"]} [{source_name}]',
                 lambda c=collector, s=runtime: c(s), all_jobs, source_stats)

    # 2) Public global Gupy candidate portal.
    #    This replaces company-by-company page scraping in normal operation.
    gupy_global_cfg = PUBLIC_SOURCES.get("gupy_global", {})
    if gupy_global_cfg.get("enabled", True):
        gupy_runtime_cfg = dict(gupy_global_cfg)
        known_gupy = set() if (full_refresh or full_discovery) else store.known_ids("gupy_global")
        if known_gupy:
            gupy_runtime_cfg["known_source_job_ids"] = known_gupy
            gupy_runtime_cfg["early_stop_known_pages"] = 2
            gupy_runtime_cfg["show_incremental_stats"] = True
        _run(
            "Gupy Global [public portal API]",
            lambda: collect_gupy_global(gupy_runtime_cfg),
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
            runtime_source = dict(source)
            if runtime_source.get("ats", "successfactors") == "successfactors":
                # Normal operation is scoped to the product's early-career
                # universe. This is source-level scope, not profile filtering.
                force_universal_sap = os.getenv(
                    "SUCCESSFACTORS_UNIVERSAL", ""
                ).strip().lower() in {"1", "true", "yes", "on"}
                if force_universal_sap:
                    runtime_source["targeted_early_career"] = False
                else:
                    runtime_source.setdefault("targeted_early_career", True)
                    runtime_source.setdefault("targeted_max_pages_per_query", 0)
                    runtime_source.setdefault("targeted_max_csb_locales", 2)
                    runtime_source.setdefault("targeted_max_queries", 16)
                    runtime_source.setdefault("targeted_max_jobs", 0)
                    runtime_source.setdefault("targeted_max_details", 25)
                    runtime_source.setdefault("targeted_max_listing_urls", 2)
                    runtime_source.setdefault("targeted_broad_fallback_pages", 1)

                tenant_prefix = f'{runtime_source["id"]}:'
                known = set() if full_refresh else store.known_ids("successfactors", prefix=tenant_prefix)
                runtime_source["known_source_job_ids"] = known
                runtime_source["targeted_query_early_stop"] = not (
                    full_refresh or full_discovery
                )
                runtime_source.setdefault(
                    "targeted_query_early_stop_known_pages", 5
                )
                runtime_source["skip_known_details"] = not full_refresh
                runtime_source["early_stop_known_pages"] = 2 if known else 0

                # v3.15.3: bounded first-sync bootstrap for new SAP tenants
                if not known and not full_refresh:
                    bootstrap_pages = max(
                        1, int(runtime_source.get("bootstrap_max_pages", 6))
                    )
                    runtime_source["max_pages_per_listing"] = min(
                        int(runtime_source.get("max_pages_per_listing", bootstrap_pages)),
                        bootstrap_pages,
                    )
                    runtime_source["max_tile_pages"] = min(
                        int(runtime_source.get("max_tile_pages", bootstrap_pages)),
                        bootstrap_pages,
                    )
                    runtime_source["max_csb_pages_per_locale"] = min(
                        int(runtime_source.get("max_csb_pages_per_locale", bootstrap_pages)),
                        bootstrap_pages,
                    )
                    runtime_source["max_listing_urls"] = min(
                        int(runtime_source.get("max_listing_urls", 10)),
                        max(1, int(runtime_source.get("bootstrap_max_listing_urls", 10))),
                    )
                    runtime_source["max_details"] = min(
                        int(runtime_source.get("max_details", 20)),
                        max(0, int(runtime_source.get("bootstrap_max_details", 20))),
                    )
                    print(
                        f'  [BOOT] {runtime_source["name"]}: primeiro sync; '
                        f'até {bootstrap_pages} páginas por rota e '
                        f'{runtime_source["max_details"]} detalhes.'
                    )
                if known and not full_discovery:
                    print(
                        f'  [CACHE] {runtime_source["name"]}: {len(known)} IDs conhecidos; '
                        "checando somente as páginas recentes primeiro."
                    )
                    probe = probe_successfactors_recent(
                        runtime_source,
                        known,
                        consecutive_known_pages=2,
                    )
                    if probe.supported:
                        print("  " + probe.summary(runtime_source["name"]))
                    if probe.safe_stop:
                        for native_id in probe.seen_native_ids & {x[len(tenant_prefix):] for x in known}:
                            store.touch(
                                "successfactors",
                                f'{runtime_source["id"]}:{native_id}',
                            )
                        source_stats["successfactors"] += len(probe.seen_native_ids & {x[len(tenant_prefix):] for x in known})
                        print(
                            f'  [FAST-STOP] {runtime_source["name"]}: nenhuma oportunidade early-career nova.'
                        )
                        continue
                    if probe.relevant_new_native_ids or probe.uncertain_new_native_ids:
                        print(
                            f'  [NOVAS] {runtime_source["name"]}: '
                            f'{len(probe.relevant_new_native_ids)} oportunidades early-career novas | '
                            f'{len(probe.uncertain_new_native_ids)} títulos insuficientes; '
                            "executando coleta SuccessFactors configurada."
                        )
            _run(
                f'{runtime_source["name"]} [{runtime_source.get("ats", "successfactors")}]',
                lambda s=runtime_source: collect_corporate_ats(s),
                all_jobs,
                source_stats,
            )


    # CP2.9) Public Brazilian internship / early-career aggregators.
    # Profiles/courses NEVER limit this collection.
    early_sources = [s for s in EARLY_CAREER_SOURCES if s.get("enabled", True)]
    if early_sources:
        print("\nFontes brasileiras especializadas em início de carreira.")
        for source in early_sources:
            runtime = dict(source)
            known = set() if full_refresh else store.known_ids(source["id"])
            runtime["known_source_job_ids"] = known
            runtime["skip_known_details"] = not full_refresh
            runtime["show_incremental_stats"] = True
            _run(
                f'{runtime["name"]} [public early-career]',
                lambda s=runtime: collect_early_career_source(s),
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
        known_99jobs = set() if (full_refresh or full_discovery) else store.known_ids("99jobs")
        _run(
            "99jobs [public_page]",
            lambda: collect_99jobs(
                cfg.get("max_jobs", 150),
                known_source_job_ids=known_99jobs,
                early_stop_known_pages=3 if known_99jobs else 0,
                show_incremental_stats=bool(known_99jobs),
            ),
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
    print(f"Vagas brutas nesta coleta: {len(all_jobs)}")

    # First dedup only exact source-native IDs. This preserves alternative
    # sources in SQLite even when the dashboard later collapses them.
    source_unique = deduplicate_source_jobs(all_jobs)
    print(f"IDs únicos nesta coleta: {len(source_unique)}")

    incremental = Counter()
    for incoming in source_unique:
        job, status, needs_processing = store.prepare(incoming)
        incremental[status] += 1
        if needs_processing:
            classify_job(job)
            enrich_job_location(job)
            store.upsert(job, commit=False)
        else:
            store.touch(job.source, job.source_job_id, commit=False)
    store.commit()

    # Do not delete/close jobs just because one run did not see them: a
    # source outage must not look like a vacancy closure. Lifecycle rules
    # are intentionally deferred to a later version.
    stored_jobs = store.load_jobs(active_only=True)
    unique = deduplicate_jobs(stored_jobs)

    print(
        "Incremental: "
        f"{incremental['new']} novas | "
        f"{incremental['changed']} alteradas | "
        f"{incremental['reprocess']} reprocessadas | "
        f"{incremental['unchanged']} reaproveitadas"
    )
    print(f"Banco persistente: {len(stored_jobs)} registros por fonte/ID")
    print(f"Vagas únicas no catálogo: {len(unique)}")

    geocoded = 0
    intent_counts = Counter()
    for job in unique:
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
        "source_unique_collected": len(source_unique),
        "unique_jobs": len(unique),
        "geocoded_jobs": geocoded,
        "incremental": dict(incremental),
        "store": store.stats(),
        "profiles": [p.id for p in profiles],
        "sources": dict(source_stats),
        "intent_counts": dict(intent_counts),
    }

    export_all(unique, profiles, matches, links, stats)
    store.close()

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
