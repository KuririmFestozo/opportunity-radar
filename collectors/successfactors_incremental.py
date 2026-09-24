"""Fast incremental probe for SAP SuccessFactors tenants."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

from collectors.common import get_text
from collectors.corporate_ats import (
    _is_priority_ref,
    _post_successfactors_json,
    _successfactors_csb_base,
    discover_successfactors_locales,
    parse_successfactors_csb_json,
    parse_successfactors_tiles,
)


@dataclass
class SuccessFactorsProbe:
    supported: bool
    safe_stop: bool
    method: str
    pages: int
    seen_native_ids: set[str]
    new_native_ids: set[str]
    reason: str = ""
    relevant_new_native_ids: set[str] = field(default_factory=set)
    uncertain_new_native_ids: set[str] = field(default_factory=set)

    @property
    def catalog_new_native_ids(self):
        # Historical new_native_ids always meant new in the broad catalog.
        return self.new_native_ids

    def summary(self, company):
        return (f"[INCREMENTAL] {company}: {self.method} | {self.pages} requests | "
                f"{len(self.seen_native_ids)} IDs verificados | "
                f"{len(self.catalog_new_native_ids)} novos catálogo | "
                f"{len(self.relevant_new_native_ids)} novos early-career | "
                f"{len(self.uncertain_new_native_ids)} sem título suficiente")


def _native_known(portal_id: str, source_ids) -> set[str]:
    prefix = f"{portal_id}:"
    out = set()
    for raw in source_ids or []:
        value = str(raw)
        if value.startswith(prefix):
            out.add(value[len(prefix):])
        elif value.isdigit():
            out.add(value)
    return out


def probe_successfactors_recent(
    config: dict,
    known_source_job_ids,
    *,
    consecutive_known_pages: int = 2,
) -> SuccessFactorsProbe:
    portal_id = str(config.get("id") or "").strip()
    known = _native_known(portal_id, known_source_job_ids)
    if not portal_id or not known:
        return SuccessFactorsProbe(False, False, "", 0, set(), set(), "sem IDs conhecidos")

    base = _successfactors_csb_base(config)
    if not base:
        return SuccessFactorsProbe(False, False, "", 0, set(), set(), "sem base CSB/RMK")

    needed = max(1, int(consecutive_known_pages or 2))

    if bool(config.get("try_tile_search", False)):
        result = _probe_tiles(base, known, needed, targeted=config.get("targeted_early_career", True))
        if result.supported:
            return result

    if bool(config.get("try_csb_json", False)):
        result = _probe_csb_json(base, config, known, needed)
        if result.supported:
            return result

    return SuccessFactorsProbe(
        False, False, "", 0, set(), set(),
        "nenhuma rota recente suportada respondeu",
    )


class _ProbePages:
    """Shared targeted policy for tiles and CSB, including incomplete titles."""

    def __init__(self, known, needed, targeted=True):
        self.known, self.needed, self.targeted = known, needed, targeted
        self.seen, self.catalog, self.relevant, self.uncertain = set(), set(), set(), set()
        self.signatures = set()
        self.streak = 0

    def observe(self, refs):
        ids = {ref.native_job_id for ref in refs if ref.native_job_id}
        if not ids:
            return bool(self.seen), "fim do catálogo" if self.seen else "página vazia sem evidência"
        signature = frozenset(ids)
        if signature in self.signatures:
            return False, "página repetida; cobertura inconclusiva"
        self.signatures.add(signature)
        self.seen |= ids
        self.catalog |= ids - self.known
        for ref in refs:
            if ref.native_job_id in self.known:
                continue
            title = ref.title.strip()
            if not self.targeted or _is_priority_ref(ref):
                self.relevant.add(ref.native_job_id)
            elif not title or title.casefold() in {"job", "vaga", "position", "opportunity"} or not any(c.isalpha() for c in title):
                self.uncertain.add(ref.native_job_id)
        if self.relevant or self.uncertain:
            return False, "novidade early-career ou título insuficiente"
        self.streak += 1
        if self.streak >= self.needed:
            return True, f"{self.streak} páginas sem novidade no escopo"
        return None, "continuar"

    def result(self, method, pages, safe, reason, supported=True):
        return SuccessFactorsProbe(supported, safe, method, pages, self.seen,
                                   self.catalog, reason, self.relevant, self.uncertain)


def _probe_tiles(base, known, needed, *, targeted=True):
    state = _ProbePages(known, needed, targeted)
    startrow = 0
    for page in range(max(needed + 1, 3)):
        url = f"{base.rstrip('/')}/tile-search-results/?" + urlencode({"startrow": startrow})
        try:
            refs = parse_successfactors_tiles(get_text(url), url, include_untitled=True)
        except Exception as exc:
            return state.result("tile", page, False, type(exc).__name__, supported=False)
        decision, reason = state.observe(refs)
        if decision is not None:
            return state.result("tile", page + 1, decision, reason, supported=bool(state.seen))
        startrow += len({ref.native_job_id for ref in refs})
    return state.result("tile", page + 1, False, "probe inconclusivo")


def _probe_csb_json(base, config, known, needed):
    locales = discover_successfactors_locales("", config)
    max_locales = max(1, min(int(config.get("fast_probe_max_locales", 3)), 5))
    api = f"{base.rstrip('/')}/services/recruiting/v1/jobs"
    requests = 0
    for locale in locales[:max_locales]:
        state = _ProbePages(known, needed, config.get("targeted_early_career", True))
        for page in range(max(needed + 1, 3)):
            try:
                payload = _post_successfactors_json(api, {
                    "keywords": "", "locale": locale, "location": "",
                    "pageNumber": page, "sortBy": "recent",
                })
                requests += 1
                refs, _ = parse_successfactors_csb_json(payload, base, locale, include_untitled=True)
            except Exception:
                # A partial response followed by an error must not imply completeness.
                if state.seen:
                    return state.result("csb_json", requests, False, "falha após resposta parcial")
                break
            decision, reason = state.observe(refs)
            if decision is not None:
                if not state.seen:
                    break
                return state.result("csb_json", requests, decision, reason)
    return SuccessFactorsProbe(False, False, "csb_json", requests, set(), set(), "probe CSB inconclusivo")
