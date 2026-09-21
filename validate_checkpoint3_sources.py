"""Live smoke test for the companies added in Checkpoint 3."""

from collectors.inhire import collect_inhire
from collectors.izirh import collect_izirh
from config.additional_ats import INHIRE_TENANTS, IZIRH_TENANTS


NEW_INHIRE = {
    "v360", "bridge", "cielo", "db1", "gx2", "aldaktecnologia",
    "jassy", "dati", "isystems", "yandeh", "iconit",
}
NEW_IZIRH = {"levva", "advice", "sertec"}


def run(registry, wanted, collector, source_name):
    print(f"\n{source_name}")
    print("-" * 72)
    for cfg in registry:
        if cfg["id"] not in wanted or not cfg.get("enabled", True):
            continue
        runtime = dict(cfg)
        runtime["known_source_job_ids"] = set()
        runtime["early_stop_known_pages"] = 0
        runtime["show_incremental_stats"] = False
        try:
            jobs = collector(runtime)
            sample = " | ".join(job.title for job in jobs[:3])
            print(
                f"[OK] {cfg['name']:<24} {len(jobs):>4} vagas"
                + (f" | {sample}" if sample else "")
            )
        except Exception as exc:
            print(
                f"[ERRO] {cfg['name']:<22} "
                f"{type(exc).__name__}: {exc}"
            )


if __name__ == "__main__":
    run(INHIRE_TENANTS, NEW_INHIRE, collect_inhire, "InHire")
    run(IZIRH_TENANTS, NEW_IZIRH, collect_izirh, "IziRH")
