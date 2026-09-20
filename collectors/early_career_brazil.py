"""Router for public Brazilian early-career sources added in Checkpoint 2.9."""
from collectors.walljobs import collect_walljobs
from collectors.cia_estagios import collect_cia_estagios
from collectors.cia_talentos import collect_cia_talentos
from collectors.nube import collect_nube
from collectors.iel import collect_iel
from collectors.superestagios import collect_superestagios

COLLECTORS = {
    "walljobs": collect_walljobs,
    "cia_estagios": collect_cia_estagios,
    "cia_talentos": collect_cia_talentos,
    "nube": collect_nube,
    "iel": collect_iel,
    "superestagios": collect_superestagios,
}


def collect_early_career_source(config: dict):
    collector_id = config.get("collector") or config.get("id")
    collector = COLLECTORS.get(collector_id)
    if collector is None:
        raise ValueError(f"Collector early-career desconhecido: {collector_id!r}")
    return collector(config)
