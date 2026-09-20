from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.successfactors import SUCCESSFACTORS_PORTALS

active = [p for p in SUCCESSFACTORS_PORTALS if p.get("enabled")]
print(f"SuccessFactors ativos: {len(active)}")
for p in active:
    print(f"  {p['id']:<22} ON  {p['name']}")
