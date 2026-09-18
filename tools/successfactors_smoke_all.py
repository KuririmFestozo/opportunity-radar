from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.corporate_ats import collect_successfactors_with_stats
from config.successfactors import SUCCESSFACTORS_PORTALS

print("SuccessFactors smoke test — 1 página / 0 detalhes por tenant")
for portal in SUCCESSFACTORS_PORTALS:
    if not portal.get("enabled"):
        continue

    cfg = dict(portal)
    cfg["max_pages_per_listing"] = 1
    cfg["max_tile_pages"] = 1
    cfg["max_csb_pages_per_locale"] = 1
    cfg["max_csb_locales"] = min(int(cfg.get("max_csb_locales", 4)), 2)
    cfg["max_listing_urls"] = 3
    cfg["max_details"] = 0
    cfg["max_jobs"] = 100
    cfg["keyword_fallback"] = False
    cfg["show_discovery_stats"] = False

    try:
        result = collect_successfactors_with_stats(cfg)
        stats = result.stats
        print(
            f"[OK] {portal['name']:<28} "
            f"{len(result.jobs):>4} jobs | "
            f"{stats.get('unique_refs', 0):>4} refs | "
            f"{stats.get('listing_pages_fetched', 0):>3} req"
        )
    except Exception as exc:
        print(
            f"[ERRO] {portal['name']:<26} "
            f"{type(exc).__name__}: {exc}"
        )
