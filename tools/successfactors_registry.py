"""Inspect or test SAP SuccessFactors portals registered in the radar."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.corporate_ats import (
    collect_successfactors_with_stats,
    validate_successfactors_portal,
)
from config.successfactors import SUCCESSFACTORS_PORTALS


def _portal_map():
    return {str(p.get("id")): p for p in SUCCESSFACTORS_PORTALS}


def _quick_config(portal: dict, *, pages: int, details: int) -> dict:
    cfg = dict(portal)
    cfg["max_pages_per_listing"] = max(1, pages)
    cfg["max_tile_pages"] = max(1, pages)
    cfg["max_csb_pages_per_locale"] = max(1, pages)
    cfg["max_csb_locales"] = 4
    cfg["max_listing_urls"] = 3
    cfg["max_jobs"] = min(int(cfg.get("max_jobs", 5000)), 100)
    cfg["max_details"] = max(0, details)
    cfg["keyword_fallback"] = False
    cfg["show_discovery_stats"] = False
    return cfg


def _print_stats(stats: dict) -> None:
    print("\nDescoberta:")
    counts = stats.get("method_counts") or {}
    if counts:
        for method, count in counts.items():
            print(f"  {method:<12} {count:>5} refs")
    else:
        print("  nenhuma referência encontrada")
    print(f"  {'somadas':<12} {stats.get('references_seen', 0):>5} refs")
    print(f"  {'únicas':<12} {stats.get('unique_refs', 0):>5} refs")
    print(f"  {'páginas/API':<12} {stats.get('listing_pages_fetched', 0):>5}")
    print(f"  {'tile req':<12} {stats.get('tile_requests', 0):>5}")
    print(f"  {'CSB JSON':<12} {stats.get('csb_json_requests', 0):>5}")
    print(f"  {'detalhes':<12} {stats.get('detail_requests', 0):>5}")
    if stats.get("errors"):
        print(f"  {'erros':<12} {len(stats['errors']):>5}")


def main():
    parser = argparse.ArgumentParser(
        description="Opportunity Radar SuccessFactors Universal Discovery v3.13.1"
    )
    parser.add_argument("portal_id", nargs="?", help="Collect only this portal id")
    parser.add_argument("--list", action="store_true", help="List configured portals")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Varre o catálogo amplo do tenant (pode demorar em empresas grandes)",
    )
    parser.add_argument("--pages", type=int, default=1, help="Páginas por rota no modo rápido")
    parser.add_argument("--details", type=int, default=3, help="Detalhes no modo rápido")
    args = parser.parse_args()

    portals = _portal_map()

    if args.list or not args.portal_id:
        print("SuccessFactors portals:")
        for portal in SUCCESSFACTORS_PORTALS:
            status = "on" if portal.get("enabled", True) else "off"
            print(f"  {portal.get('id'):<20} {status:<3} {portal.get('name')}")
        if not args.portal_id:
            return

    portal = portals.get(args.portal_id)
    if not portal:
        raise SystemExit(f"Portal não encontrado: {args.portal_id}")
    validate_successfactors_portal(portal)

    if args.full:
        cfg = dict(portal)
        cfg["show_discovery_stats"] = False
        print(f"[FULL] Varredura universal de {portal['name']}...")
    else:
        cfg = _quick_config(portal, pages=max(1, args.pages), details=max(0, args.details))
        print(
            f"[RÁPIDO] {portal['name']}: tiles RMK + CSB JSON + HTML/XML; "
            f"até {cfg['max_pages_per_listing']} página(s) por rota/locale e {cfg['max_details']} detalhe(s)."
        )

    print("Acessando portal...")
    result = collect_successfactors_with_stats(cfg)
    _print_stats(result.stats)

    print(f"\n{portal['name']}: {len(result.jobs)} vagas únicas")
    for job in result.jobs[:20]:
        methods = ",".join(job.metadata.get("discovery_methods") or [])
        suffix = f" [{methods}]" if methods else ""
        print(
            f"  {job.source_job_id} | {job.title} | "
            f"{job.location or 'local não informado'}{suffix}"
        )

    if not args.full:
        print("\nPara varrer o tenant completo:")
        print(f"  python tools/successfactors_registry.py {args.portal_id} --full")


if __name__ == "__main__":
    main()
