"""Live smoke test for CP3.1 source expansion."""
from collectors.bettha import collect_bettha
from collectors.cargill import collect_cargill
from collectors.matchbox import collect_matchbox
from collectors.superestagios import collect_superestagios
from collectors.taqe import collect_taqe
from collectors.smartrecruiters import collect_smartrecruiters
from collectors.workday import collect_workday
from config.additional_ats import SMARTRECRUITERS_BOARDS, WORKDAY_BOARDS
from config.sources import PUBLIC_SOURCES


def show(name, fn):
    try:
        jobs = fn()
        sample = " | ".join(job.title for job in jobs[:3])
        suffix = f" | {sample}" if sample else ""
        print(f"[OK] {name:<24} {len(jobs):>5} vagas{suffix}")
    except Exception as exc:
        print(f"[ERRO] {name:<22} {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    show("TAQE", lambda: collect_taqe({
        "max_jobs": 0,
        "show_incremental_stats": False,
    }))
    show("Bettha", lambda: collect_bettha({
        "max_jobs": 0,
        "show_incremental_stats": False,
    }))
    show("Matchbox", lambda: collect_matchbox({
        "max_jobs": 0,
        "show_incremental_stats": False,
    }))
    show("Super Estágios", lambda: collect_superestagios({
        "list_pages": [
            {"url": "https://www.superestagios.com.br/vagas/engenharia", "city": ""}
        ],
        "max_jobs": 0,
    }))
    show("Cargill", lambda: collect_cargill({
        **PUBLIC_SOURCES["cargill"],
        "max_pages": 2,
        "max_jobs": 100,
    }))

    for cfg in WORKDAY_BOARDS:
        if cfg["id"] in {"dow", "airliquide", "jj", "bakerhughes"}:
            runtime = dict(cfg)
            runtime.update(
                queries=["intern", "estágio"],
                max_pages_per_query=1,
                max_jobs=60,
            )
            show(cfg["name"], lambda s=runtime: collect_workday(s))

    for cfg in SMARTRECRUITERS_BOARDS:
        if cfg["id"] in {"syngenta", "sgs", "wabtec"}:
            runtime = dict(cfg)
            runtime.update(
                queries=["intern", "estágio"],
                max_pages_per_query=1,
                max_jobs=120,
            )
            show(cfg["name"], lambda s=runtime: collect_smartrecruiters(s))
