"""Fast incremental probe for SAP SuccessFactors tenants."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from collectors.common import get_text
from collectors.corporate_ats import (
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
        result = _probe_tiles(base, known, needed)
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


def _probe_tiles(base: str, known: set[str], needed: int) -> SuccessFactorsProbe:
    seen: set[str] = set()
    new: set[str] = set()
    pages = 0
    known_streak = 0
    startrow = 0
    previous: set[str] = set()

    for _ in range(max(needed + 1, 3)):
        url = f"{base.rstrip('/')}/tile-search-results/?" + urlencode({"startrow": startrow})
        try:
            html = get_text(url)
        except Exception as exc:
            return SuccessFactorsProbe(
                False, False, "tile", pages, seen, new,
                f"{type(exc).__name__}: {exc}",
            )

        pages += 1
        refs = parse_successfactors_tiles(html, url)
        ids = {ref.native_job_id for ref in refs if ref.native_job_id}

        if not ids:
            if seen and not new and known_streak >= 1:
                return SuccessFactorsProbe(
                    True, True, "tile", pages, seen, new,
                    "fim do catálogo recente",
                )
            return SuccessFactorsProbe(
                False, False, "tile", pages, seen, new, "tile vazio",
            )

        if ids == previous:
            unknown = ids - known
            if unknown:
                return SuccessFactorsProbe(
                    True, False, "tile", pages, seen | ids, unknown,
                    "página repetida com ID novo",
                )
            return SuccessFactorsProbe(
                True, True, "tile", pages, seen | ids, new,
                "página repetida e conhecida",
            )

        previous = ids
        seen |= ids
        unknown = ids - known
        if unknown:
            new |= unknown
            return SuccessFactorsProbe(
                True, False, "tile", pages, seen, new, "ID novo encontrado",
            )

        known_streak += 1
        if known_streak >= needed:
            return SuccessFactorsProbe(
                True, True, "tile", pages, seen, new,
                f"{known_streak} páginas só conhecidas",
            )

        startrow += len(ids)

    return SuccessFactorsProbe(
        True, False, "tile", pages, seen, new, "probe inconclusivo",
    )


def _probe_csb_json(base: str, config: dict, known: set[str], needed: int) -> SuccessFactorsProbe:
    locales = discover_successfactors_locales("", config)
    max_locales = max(1, min(int(config.get("fast_probe_max_locales", 3)), 5))
    api = f"{base.rstrip('/')}/services/recruiting/v1/jobs"

    total_seen: set[str] = set()
    total_new: set[str] = set()
    requests = 0
    any_supported = False

    for locale in locales[:max_locales]:
        known_streak = 0
        locale_seen = False

        for page in range(max(needed, 2)):
            try:
                payload = _post_successfactors_json(
                    api,
                    {
                        "keywords": "",
                        "locale": locale,
                        "location": "",
                        "pageNumber": page,
                        "sortBy": "recent",
                    },
                )
            except Exception:
                break

            requests += 1
            refs, _ = parse_successfactors_csb_json(payload, base, locale)
            ids = {ref.native_job_id for ref in refs if ref.native_job_id}
            if not ids:
                break

            any_supported = True
            locale_seen = True
            total_seen |= ids
            unknown = ids - known
            if unknown:
                total_new |= unknown
                return SuccessFactorsProbe(
                    True, False, "csb_json", requests,
                    total_seen, total_new, f"ID novo em {locale}",
                )

            known_streak += 1
            if known_streak >= needed:
                return SuccessFactorsProbe(
                    True, True, "csb_json", requests,
                    total_seen, total_new,
                    f"{known_streak} páginas só conhecidas em {locale}",
                )

        if locale_seen and not total_new:
            configured = list(config.get("csb_locales") or [])
            if len(configured) == 1:
                return SuccessFactorsProbe(
                    True, True, "csb_json", requests,
                    total_seen, total_new,
                    f"locale único {locale} completamente conhecido",
                )

    return SuccessFactorsProbe(
        any_supported, False, "csb_json", requests,
        total_seen, total_new, "probe CSB inconclusivo",
    )
