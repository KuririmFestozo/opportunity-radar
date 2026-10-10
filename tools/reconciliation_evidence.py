"""Read-only CP5 classification and collection-coverage evidence.

This module does not import database drivers and never selects a winning
snapshot. Metrics are opportunity-based for classification and scope-based
for collection; no automatic lifecycle write is ever authorized.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def _timestamp(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = (value if isinstance(value, datetime) else
                  datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_score_drift(
    sqlite_opportunity_ids: set[str],
    postgres_opportunity_ids: set[str],
    sqlite_scores: Mapping[str, Mapping[str, int]],
    postgres_scores: Mapping[str, Mapping[str, int]],
    sqlite_expected: Mapping[str, Mapping[str, int]] | None = None,
    postgres_expected: Mapping[str, Mapping[str, int]] | None = None,
    *,
    max_samples: int = 5,
) -> dict[str, Any]:
    """Partition score drift into missing course keys vs changed values."""
    if max_samples < 1:
        raise ValueError("max_samples deve ser >= 1")

    counts: Counter[str] = Counter()
    only_sqlite_courses: Counter[str] = Counter()
    only_postgres_courses: Counter[str] = Counter()
    changed_value_courses: Counter[str] = Counter()
    sqlite_course_count: Counter[str] = Counter()
    postgres_course_count: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []

    shared = sorted(sqlite_opportunity_ids & postgres_opportunity_ids)
    for opportunity_id in shared:
        left = sqlite_scores.get(opportunity_id, {})
        right = postgres_scores.get(opportunity_id, {})
        sqlite_course_count[str(len(left))] += 1
        postgres_course_count[str(len(right))] += 1

        missing_pg = set(left) - set(right)
        missing_sqlite = set(right) - set(left)
        changed = {course for course in set(left) & set(right)
                   if int(left[course]) != int(right[course])}
        if not (missing_pg or missing_sqlite or changed):
            counts["same_course_scores"] += 1
            continue

        counts["course_scores_mismatch"] += 1
        counts["missing_postgres_course_cells"] += len(missing_pg)
        counts["missing_sqlite_course_cells"] += len(missing_sqlite)
        counts["changed_shared_course_values"] += len(changed)
        only_sqlite_courses.update(sorted(missing_pg))
        only_postgres_courses.update(sorted(missing_sqlite))
        changed_value_courses.update(sorted(changed))
        if missing_pg and not missing_sqlite and not changed:
            category = "sqlite_extra_course_keys_only"
        elif missing_sqlite and not missing_pg and not changed:
            category = "postgres_extra_course_keys_only"
        elif changed and not missing_pg and not missing_sqlite:
            category = "shared_course_values_only"
        else:
            category = "mixed_course_differences"
        counts[category] += 1

        if sqlite_expected is not None:
            if left == sqlite_expected.get(opportunity_id, {}):
                counts["sqlite_relational_matches_payload"] += 1
            else:
                counts["sqlite_relational_differs_from_payload"] += 1
        if postgres_expected is not None:
            if right == postgres_expected.get(opportunity_id, {}):
                counts["postgres_relational_matches_payload"] += 1
            else:
                counts["postgres_relational_differs_from_payload"] += 1
        if (sqlite_expected is not None and postgres_expected is not None and
                left == sqlite_expected.get(opportunity_id, {}) and
                right == postgres_expected.get(opportunity_id, {})):
            counts["both_relational_match_own_payload"] += 1

        if len(samples) < max_samples:
            samples.append({
                "opportunity_id": opportunity_id,
                "category": category,
                "sqlite_course_count": len(left),
                "postgres_course_count": len(right),
                "missing_postgres_courses": sorted(missing_pg),
                "missing_sqlite_courses": sorted(missing_sqlite),
                "changed_value_courses": sorted(changed),
            })

    return {
        "shared_opportunities": len(shared),
        "metrics": dict(sorted(counts.items())),
        "course_count_distribution": {
            "sqlite": dict(sorted(sqlite_course_count.items(), key=lambda it: int(it[0]))),
            "postgres": dict(sorted(postgres_course_count.items(), key=lambda it: int(it[0]))),
        },
        "courses_missing_from_postgres": dict(sorted(only_sqlite_courses.items())),
        "courses_missing_from_sqlite": dict(sorted(only_postgres_courses.items())),
        "courses_with_changed_values": dict(sorted(changed_value_courses.items())),
        "samples": samples,
        "automatic_reclassification_authorized": False,
        "note": "Course-key drift can reflect classification catalog evolution, not necessarily corruption. Match to each side's normalized payload first.",
    }


def compare_collection_scopes(
    sqlite_rows: Iterable[Any],
    postgres_rows: Iterable[Any],
    *,
    posting_sources: Iterable[str] = (),
    max_samples: int = 5,
) -> dict[str, Any]:
    """Assess coverage metadata, never infer closure from a source absence."""
    if max_samples < 1:
        raise ValueError("max_samples deve ser >= 1")

    def index(rows: Iterable[Any]) -> dict[tuple[str, str], dict[str, Any]]:
        found = {}
        for raw in rows:
            item = dict(raw)
            key = str(item["source"]), str(item["scope_key"])
            if not all(key):
                raise ValueError("Escopo com source ou scope_key vazio")
            if key in found:
                raise ValueError(f"Escopo duplicado: {key!r}")
            found[key] = item
        return found

    left, right = index(sqlite_rows), index(postgres_rows)
    lkeys, rkeys = set(left), set(right)
    shared = sorted(lkeys & rkeys)
    metrics: Counter[str] = Counter()
    per_source: dict[str, Counter[str]] = defaultdict(Counter)
    samples: list[dict[str, Any]] = []

    for source, _ in lkeys - rkeys:
        per_source[source]["sqlite_only"] += 1
    for source, _ in rkeys - lkeys:
        per_source[source]["postgres_only"] += 1

    for key in shared:
        a, b = left[key], right[key]
        source = key[0]
        if str(a["last_coverage"]) != str(b["last_coverage"]):
            metrics["coverage_label_mismatch"] += 1
            per_source[source]["coverage_label_mismatch"] += 1
        run_a, run_b = _timestamp(a["last_run_at"]), _timestamp(b["last_run_at"])
        if run_a is None or run_b is None:
            category = "unknown_run_recency"
        elif run_a > run_b:
            category = "sqlite_run_newer"
        elif run_b > run_a:
            category = "postgres_run_newer"
        else:
            category = "same_run_timestamp"
        metrics[category] += 1
        per_source[source][category] += 1
        if (str(a["last_coverage"]) == "complete" and
                run_a is not None and (run_b is None or run_a > run_b)):
            metrics["sqlite_complete_run_newer_candidate_evidence"] += 1
            if len(samples) < max_samples:
                samples.append({"source": source, "scope_key": key[1],
                                "sqlite_last_run": run_a.isoformat(),
                                "postgres_last_run": run_b.isoformat() if run_b else None})
        if int(a["successful_runs"] or 0) != int(b["successful_runs"] or 0):
            metrics["successful_run_count_mismatch"] += 1

    known = {s for s, _ in lkeys | rkeys}
    return {
        "sqlite_scopes": len(left),
        "postgres_scopes": len(right),
        "shared_scopes": len(shared),
        "sqlite_only_scopes": len(lkeys - rkeys),
        "postgres_only_scopes": len(rkeys - lkeys),
        "posting_sources_without_scope_history": sorted(set(posting_sources) - known),
        "metrics": dict(sorted(metrics.items())),
        "per_source": {k: dict(sorted(v.items())) for k, v in sorted(per_source.items())},
        "candidate_complete_run_samples": samples,
        "automatic_lifecycle_updates_authorized": False,
        "note": "Complete scope runs alone cannot prove each posting was covered. Check source-specific scope mapping and collector health before any inactivity transition.",
    }
