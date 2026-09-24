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
from collectors.cargill import collect_cargill

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
from processing.deduplicate import deduplicate_source_jobs
from storage.sqlite_repository import SQLiteOpportunityRepository
from storage.incremental_state import (
    known_discovery_ids,
    needs_full_audit,
)


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
                "chemical_engineering_internship_br,"
                "summer_br"
            ),
        ).split(",")
        if x.strip()
    ]
    profiles = [PROFILES[x] for x in requested if x in PROFILES]
    return profiles or list(PROFILES.values())


def additional_ats_runtime(
    source,
    source_name,
    store,
    full_refresh,
    full_discovery=False,
    daily_audit=False,
    unbounded_collection=False,
):
    runtime = dict(source)
    prefix = f"{source['id']}:"
    scope_key = prefix
    if hasattr(store, "needs_full_audit"):
        periodic_full = store.needs_full_audit(
            source_name,
            scope_key,
            every_runs=int(source.get("full_audit_every_runs", 7)),
        )
    elif hasattr(store, "conn"):
        # Backward compatibility for JobStore-based tests during CP4.
        periodic_full = needs_full_audit(
            store,
            source_name,
            scope_key,
            every_runs=int(source.get("full_audit_every_runs", 7)),
        )
    else:
        periodic_full = False
    force_full_scan = bool(
        full_refresh or full_discovery or daily_audit or periodic_full
    )

    runtime["_scope_prefix"] = prefix
    runtime["_scope_key"] = scope_key
    runtime["_periodic_full_audit"] = periodic_full
    if full_refresh:
        runtime["known_source_job_ids"] = set()
    elif hasattr(store, "known_discovery_ids"):
        runtime["known_source_job_ids"] = store.known_discovery_ids(
            source_name, prefix=prefix
        )
    elif hasattr(store, "conn"):
        # Backward compatibility for JobStore-based tests during CP4.
        runtime["known_source_job_ids"] = known_discovery_ids(
            store, source_name, prefix=prefix
        )
    elif hasattr(store, "known_posting_ids"):
        # Repository contract.
        runtime["known_source_job_ids"] = store.known_posting_ids(
            source_name, prefix=prefix
        )
    else:
        # Backward-compatible fallback for lightweight tests/adapters.
        runtime["known_source_job_ids"] = store.known_ids(
            source_name, prefix=prefix
        )
    runtime["early_stop_known_pages"] = 0 if force_full_scan else 2
    # Audits traverse listings but still reuse known detail content.
    runtime["skip_known_details"] = not full_refresh
    runtime["show_incremental_stats"] = True
    if unbounded_collection:
        runtime.update({
            "max_jobs": 100000,
            "max_pages": 1000,
            "max_details": 100000,
            "max_pages_per_query": 1000,
        })
    return runtime


def main():
    profiles = active_profiles()
    all_jobs = []
    source_stats = Counter()
    store = SQLiteOpportunityRepository()
    bootstrap = store.bootstrap_from_json(Path("output/jobs.json"))
    full_refresh = os.getenv("FULL_REFRESH", "").strip().lower() in {"1", "true", "yes", "on"}
    full_discovery = os.getenv("FULL_DISCOVERY", "").strip().lower() in {"1", "true", "yes", "on"}
    daily_audit = os.getenv("DAILY_AUDIT", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    unbounded_collection = os.getenv("UNBOUNDED_COLLECTION", "").strip().lower() in {
        "1", "true", "yes", "on"
    }

    print("=" * 86)
    print(" OPPORTUNITY RADAR v3.17.0 — UFSCar ENGINEERING + SOURCE EXPANSION")
    print("=" * 86)
    print("Perfis ativos são apenas presets de filtro; NÃO limitam a coleta.")
    if bootstrap["imported"]:
        print(f"Banco incremental criado do jobs.json: {bootstrap['imported']} vagas preservadas.")
    else:
        print(f"Banco incremental: {store.count_postings()} registros armazenados.")
    if full_refresh:
        print("Modo FULL_REFRESH: early-stop e cache de detalhes desativados nesta execução.")
    elif full_discovery:
        print("Modo FULL_DISCOVERY: baseline exaustivo; early-stops incrementais desativados.")
    elif daily_audit:
        print(
            "Modo DAILY_AUDIT: varredura completa de listagens; "
            "early-stops desativados, cache de detalhes preservado e lifecycle habilitado."
        )
    else:
        print("Modo incremental: early-stop ativo para fontes paginadas com IDs conhecidos.")
    if unbounded_collection:
        print("Modo UNBOUNDED_COLLECTION: sem tetos de produto; somente guard rails técnicos.")
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
            runtime = additional_ats_runtime(
                source,
                source_name,
                store,
                full_refresh,
                full_discovery,
                daily_audit,
                unbounded_collection,
            )
            if runtime.get("_periodic_full_audit"):
                print(
                    f'  [AUDIT] {source["name"]}: varredura completa periódica '
                    "para validar ciclo de vida."
                )
            collected = _run(
                f'{source["name"]} [{source_name}]',
                lambda c=collector, s=runtime: c(s),
                all_jobs,
                source_stats,
            )
            if collected is not None:
                seen_ids = set(
                    runtime.get("_run_seen_ids")
                    or {job.source_job_id for job in collected}
                )
                coverage = str(runtime.get("_run_coverage") or "partial")
                life = store.reconcile_scope(
                    source_name,
                    seen_ids,
                    prefix=runtime["_scope_prefix"],
                    coverage=coverage,
                    miss_threshold=int(
                        source.get("missing_grace_complete_runs", 2)
                    ),
                )
                store.finish_scope_run(
                    source_name,
                    runtime["_scope_key"],
                    coverage=coverage,
                )
                if coverage == "complete" and (
                    life["new_missing"] or life["inactivated"]
                ):
                    print(
                        f'  [LIFECYCLE] {source["name"]}: '
                        f'{life["new_missing"]} novas ausências | '
                        f'{life["inactivated"]} inativadas.'
                    )

    # 2) Public global Gupy candidate portal.
    #    This replaces company-by-company page scraping in normal operation.
    gupy_global_cfg = PUBLIC_SOURCES.get("gupy_global", {})
    if gupy_global_cfg.get("enabled", True):
        gupy_runtime_cfg = dict(gupy_global_cfg)
        if unbounded_collection:
            gupy_runtime_cfg["max_pages_per_native_type"] = 500
            gupy_runtime_cfg["max_pages_per_keyword"] = 500
        known_gupy = (
            set()
            if full_refresh
            else store.known_discovery_ids( "gupy_global")
        )
        if known_gupy:
            gupy_runtime_cfg["known_source_job_ids"] = known_gupy
            gupy_runtime_cfg["early_stop_known_pages"] = (
                0 if (full_discovery or daily_audit) else 2
            )
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

                if unbounded_collection:
                    runtime_source["targeted_max_pages_per_query"] = 1000
                    runtime_source["targeted_max_queries"] = 128
                    runtime_source["targeted_max_jobs"] = 100000
                    runtime_source["targeted_max_details"] = 2500
                    runtime_source["max_pages_per_listing"] = 1000
                    runtime_source["max_tile_pages"] = 1000
                    runtime_source["max_csb_pages_per_locale"] = 1000
                    runtime_source["max_details"] = 2500
                
                tenant_prefix = f'{runtime_source["id"]}:'
                catalog_known = store.known_posting_ids(
                    "successfactors",
                    prefix=tenant_prefix,
                )
                known = (
                    set()
                    if full_refresh
                    else store.known_discovery_ids(
                        "successfactors",
                        prefix=tenant_prefix,
                    )
                )
                runtime_source["known_source_job_ids"] = known
                runtime_source["targeted_query_early_stop"] = not (
                    full_refresh or full_discovery or daily_audit
                )
                runtime_source.setdefault(
                    "targeted_query_early_stop_known_pages", 5
                )
                runtime_source["skip_known_details"] = not full_refresh
                runtime_source["early_stop_known_pages"] = (
                    0 if daily_audit else (2 if known else 0)
                )

                # v3.15.3: bounded first-sync bootstrap for new SAP tenants
                if not known and not (
                    full_refresh or full_discovery or daily_audit
                ):
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
                if known and not (full_discovery or daily_audit):
                    print(
                        f'  [CACHE] {runtime_source["name"]}: {len(known)} IDs conhecidos; '
                        "checando somente as páginas recentes primeiro."
                    )
                    probe = probe_successfactors_recent(
                        runtime_source,
                        known,
                        consecutive_known_pages=2,
                    )
                    seen_catalog_native = set()
                    if probe.supported:
                        print("  " + probe.summary(runtime_source["name"]))
                        catalog_native = {
                            value[len(tenant_prefix):]
                            for value in catalog_known
                            if value.startswith(tenant_prefix)
                        }
                        seen_catalog_native = (
                            probe.seen_native_ids & catalog_native
                        )
                        unresolved = (
                            probe.relevant_new_native_ids
                            | probe.uncertain_new_native_ids
                        )
                        out_of_scope = (
                            probe.seen_native_ids
                            - catalog_native
                            - unresolved
                        )
                        if out_of_scope:
                            store.record_discoveries(
                                "successfactors",
                                {
                                    f'{runtime_source["id"]}:{native_id}'
                                    for native_id in out_of_scope
                                },
                                scope_status="out_of_scope",
                            )
                        if seen_catalog_native:
                            store.mark_seen_ids(
                                "successfactors",
                                {
                                    f'{runtime_source["id"]}:{native_id}'
                                    for native_id in seen_catalog_native
                                },
                            )
                    if probe.safe_stop:
                        source_stats["successfactors"] += len(
                            seen_catalog_native
                        )
                        print(
                            f'  [INCREMENTAL-STOP] {runtime_source["name"]}: nenhuma oportunidade early-career nova.'
                        )
                        continue
                    if probe.relevant_new_native_ids or probe.uncertain_new_native_ids:
                        print(
                            f'  [NOVAS] {runtime_source["name"]}: '
                            f'{len(probe.relevant_new_native_ids)} oportunidades early-career novas | '
                            f'{len(probe.uncertain_new_native_ids)} títulos insuficientes; '
                            "executando coleta SuccessFactors configurada."
                        )
            collected = _run(
                f'{runtime_source["name"]} [{runtime_source.get("ats", "successfactors")}]',
                lambda s=runtime_source: collect_corporate_ats(s),
                all_jobs,
                source_stats,
            )
            if (
                daily_audit
                and collected is not None
                and runtime_source.get("ats", "successfactors") == "successfactors"
            ):
                coverage = str(
                    runtime_source.get("_run_coverage") or "partial"
                )
                life = store.reconcile_scope(
                    "successfactors",
                    runtime_source.get("_run_seen_ids")
                    or {job.source_job_id for job in collected},
                    prefix=f'{runtime_source["id"]}:',
                    coverage=coverage,
                    miss_threshold=int(
                        runtime_source.get(
                            "missing_grace_complete_runs", 2
                        )
                    ),
                )
                store.finish_scope_run(
                    "successfactors",
                    f'{runtime_source["id"]}:',
                    coverage=coverage,
                )
                if coverage == "complete" and (
                    life["new_missing"] or life["inactivated"]
                ):
                    print(
                        f'  [LIFECYCLE] {runtime_source["name"]}: '
                        f'{life["new_missing"]} novas ausências | '
                        f'{life["inactivated"]} inativadas.'
                    )


    cargill_cfg = PUBLIC_SOURCES.get("cargill", {})
    if cargill_cfg.get("enabled", True):
        cargill_runtime = dict(cargill_cfg)
        if unbounded_collection:
            cargill_runtime["max_pages"] = 500
            cargill_runtime["max_jobs"] = 100000
        _run(
            "Cargill [official careers]",
            lambda: collect_cargill(cargill_runtime),
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
            known = set() if full_refresh else store.known_posting_ids(source["id"])
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
            0 if unbounded_collection else cfg.get("max_collection_queries", 60)
        )
        print(f"\nColeta ampla Vagas.com: {len(queries)} consultas independentes dos perfis.")
        for query in queries:
            _run(
                f"Vagas.com [{query}]",
                lambda q=query: collect_vagas_com(
                    q,
                    0 if unbounded_collection else cfg.get("max_jobs_per_query", 80),
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
        known_99jobs = (
            set()
            if full_refresh
            else store.known_discovery_ids( "99jobs")
        )
        _run(
            "99jobs [public_page]",
            lambda: collect_99jobs(
                0 if unbounded_collection else cfg.get("max_jobs", 9999),
                known_source_job_ids=known_99jobs,
                early_stop_known_pages=(
                    0
                    if (full_discovery or daily_audit)
                    else (3 if known_99jobs else 0)
                ),
                show_incremental_stats=bool(known_99jobs),
                max_pages_per_search=1000 if unbounded_collection else 4,
                max_global_pages=1000 if unbounded_collection else 150,
            ),
            all_jobs,
            source_stats,
        )

    summer_cfg = PUBLIC_SOURCES.get("summer_br", {})
    if summer_cfg.get("enabled", True):
        summer_runtime = dict(summer_cfg)
        if unbounded_collection:
            summer_runtime.update({
                "summer_native_pages": 0,
                "summer_keyword_pages": 0,
                "jobs99_pages_per_term": 0,
                "jobs99_max_jobs": 0,
                "vagas_max_jobs_per_query": 0,
            })
        print("\nBusca dedicada Brasil — férias/verão (categoria rara).")
        if summer_cfg.get("gupy_enabled", True):
            _run(
                "Gupy [Summer/Férias BR dedicado]",
                lambda: collect_gupy_summer_br({**gupy_global_cfg, **summer_runtime}),
                all_jobs,
                source_stats,
            )
        if summer_cfg.get("jobs99_enabled", True):
            _run(
                "99jobs [Summer/Férias BR dedicado]",
                lambda: collect_99jobs_summer_br(summer_runtime),
                all_jobs,
                source_stats,
            )
        if summer_cfg.get("vagas_com_enabled", True):
            _run(
                "Vagas.com [Summer/Férias BR dedicado]",
                lambda: collect_vagas_summer_br(summer_runtime),
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
        job, status, needs_processing = store.prepare_posting(incoming)
        incremental[status] += 1
        if needs_processing:
            classify_job(job)
            enrich_job_location(job)
            store.upsert_posting(job, commit=False)
        else:
            store.touch_posting(job.source, job.source_job_id, commit=False)

    seen_state = store.mark_seen_postings(source_unique)
    store.commit()

    # CP4-A shadow migration: legacy jobs remain authoritative for now.
    # The relational schema is synchronized only after a successful batch.
    unified_state = store.sync_unified_schema()

    # CP4-E: read the user-facing catalog from relational opportunities.
    unique = store.load_opportunities(active_only=True)

    print(
        "Incremental: "
        f"{incremental['new']} novas | "
        f"{incremental['changed']} alteradas | "
        f"{incremental['reprocess']} reprocessadas | "
        f"{incremental['unchanged']} reaproveitadas"
    )
    life_stats = store.lifecycle_stats()
    print(f"Banco persistente ativo: {life_stats['active']} registros por fonte/ID")
    print(f"Vagas únicas no catálogo: {len(unique)}")
    print(
        "Persistência CP4-C: "
        f"{unified_state['source_postings']} postings | "
        f"{unified_state['opportunities']} opportunities | "
        f"{unified_state['active_opportunities']} ativas | "
        f"{unified_state['cross_source_opportunities']} cross-source | "
        f"schema v{unified_state['schema_version']}"
    )
    print(
        "Lifecycle: "
        f"{life_stats['active']} ativas | "
        f"{life_stats['missing']} em observação | "
        f"{life_stats['inactive']} inativas | "
        f"{life_stats['out_of_scope_discoveries']} IDs fora do escopo lembrados"
    )
    if seen_state["reopened"]:
        print(
            f"Lifecycle: {seen_state['reopened']} vaga(s) reaberta(s) "
            "nesta execução."
        )

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
        "lifecycle": life_stats,
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
        return jobs
    except KeyboardInterrupt:
        print(f"\n[INTERROMPIDO] {label}")
        raise
    except Exception as exc:
        print(
            f"[ERRO] {label:<60} "
            f"{type(exc).__name__}: {exc}"
        )
        return None


if __name__ == "__main__":
    main()
