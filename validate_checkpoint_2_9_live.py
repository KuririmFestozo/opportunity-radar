from config.early_career_sources import EARLY_CAREER_SOURCES
from collectors.early_career_brazil import collect_early_career_source

print("=" * 80)
print("CHECKPOINT 2.9 - VALIDACAO AO VIVO")
print("=" * 80)

for source in EARLY_CAREER_SOURCES:
    print()
    print("-" * 80)
    print(f"{source['name']} | enabled={source.get('enabled', True)}")

    if not source.get("enabled", True):
        print(f"[SKIP] {source.get('disabled_reason', 'desativado')}")
        continue

    cfg = dict(source)
    cfg["show_incremental_stats"] = True
    cfg["max_jobs"] = min(int(cfg.get("max_jobs", 100)), 100)

    try:
        jobs = collect_early_career_source(cfg)

        print(f"[RESULTADO] {len(jobs)} vagas")

        for job in jobs[:5]:
            print(
                f"  {job.source_job_id} | "
                f"{job.company} | "
                f"{job.title} | "
                f"{job.location} | "
                f"{job.salary or '-'}"
            )

    except Exception as exc:
        print(f"[ERRO] {type(exc).__name__}: {exc}")
