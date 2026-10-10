"""CP5: conservative, read-only SQLite/PostgreSQL reconciliation preview.

The report proposes *candidates*, never writes or chooses a winning snapshot.
Usage (DATABASE_URL configured):
    python -m tools.plan_postgres_reconciliation \
        --db data/snapshots/main-20261010.db \
        --output data/snapshots/cp5-reconciliation.json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


POSTINGS_SQL = """
SELECT source, source_job_id, opportunity_id, raw_hash, processing_version,
       first_seen_at, last_seen_at, last_changed_at, last_checked_at,
       is_active, miss_count, missing_since, inactive_at, association_method
FROM source_postings
"""
SCORES_SQL = "SELECT opportunity_id, course_id, score FROM opportunity_course_scores"
INTENTS_SQL = "SELECT opportunity_id, intent_id FROM opportunity_intents"
SQLITE_PAYLOAD_SQL = """
SELECT source, source_job_id,
       json_extract(normalized_job_json, '$.course_scores') AS scores
FROM source_postings
"""
POSTGRES_PAYLOAD_SQL = """
SELECT source, source_job_id,
       (normalized_job_json -> 'course_scores')::text AS scores
FROM public.source_postings
"""


def _time(value: Any) -> datetime | None:
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


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["source"]), str(row["source_job_id"])


def _postings(rows: Iterable[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for raw in rows:
        row = dict(raw)
        key = _key(row)
        if not all(key):
            raise ValueError("source e source_job_id nao podem ser vazios")
        if key in result:
            raise ValueError(f"Identidade duplicada: {key!r}")
        result[key] = row
    return result


def _rel_scores(rows: Iterable[Any]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(dict)
    for row in rows:
        opportunity_id, course_id = str(row["opportunity_id"]), str(row["course_id"])
        if course_id in result[opportunity_id]:
            raise ValueError(f"Score duplicado: {opportunity_id}/{course_id}")
        result[opportunity_id][course_id] = int(row["score"])
    return result


def _rel_intents(rows: Iterable[Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        result[str(row["opportunity_id"])].add(str(row["intent_id"]))
    return result


def _payload_scores(
    rows: Iterable[Any], postings: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, dict[str, int]]:
    """Rebuild each opportunity's expected scores from its source JSON payloads."""
    expected: dict[str, dict[str, int]] = defaultdict(dict)
    observed: set[tuple[str, str]] = set()
    for row in rows:
        key = _key(row)
        if key in observed:
            raise ValueError(f"Payload duplicado: {key!r}")
        observed.add(key)
        if key not in postings:
            raise ValueError(f"Payload desconhecido: {key!r}")
        raw_scores = row["scores"]
        try:
            values = json.loads(raw_scores) if isinstance(raw_scores, str) else raw_scores
        except json.JSONDecodeError as exc:
            raise ValueError(f"course_scores JSON invalido: {key!r}") from exc
        if values is None:
            values = {}
        if not isinstance(values, dict):
            raise ValueError(f"course_scores nao e objeto: {key!r}")
        dest = expected[str(postings[key]["opportunity_id"])]
        for course, value in values.items():
            course = str(course)
            score = int(value)
            dest[course] = max(dest.get(course, 0), score)
    if observed != set(postings):
        raise ValueError("Carga de payloads incompleta")
    return expected


def build_reconciliation_plan(
    sqlite_postings: Iterable[Any],
    postgres_postings: Iterable[Any],
    *,
    sqlite_scores: Iterable[Any] = (),
    postgres_scores: Iterable[Any] = (),
    sqlite_intents: Iterable[Any] = (),
    postgres_intents: Iterable[Any] = (),
    sqlite_payloads: Iterable[Any] | None = None,
    postgres_payloads: Iterable[Any] | None = None,
    max_samples: int = 5,
) -> dict[str, Any]:
    """Pure, deterministic snapshot analysis. All proposed writes remain blocked."""
    if max_samples < 1:
        raise ValueError("max_samples deve ser >= 1")
    left, right = _postings(sqlite_postings), _postings(postgres_postings)
    keys_left, keys_right = set(left), set(right)
    shared = sorted(keys_left & keys_right)
    only_left = sorted(keys_left - keys_right)
    only_right = sorted(keys_right - keys_left)
    per_source: dict[str, Counter[str]] = defaultdict(Counter)
    conflicts: Counter[str] = Counter()
    newer: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def count(key: tuple[str, str], field: str, *, details: dict[str, Any] | None = None) -> None:
        per_source[key[0]][field] += 1
        if details is not None and len(samples[field]) < max_samples:
            samples[field].append({"source": key[0], "source_job_id": key[1], **details})

    pg_op_ids = {str(row["opportunity_id"]) for row in right.values()}
    sqlite_op_ids = {str(row["opportunity_id"]) for row in left.values()}
    for key in only_left:
        row = left[key]
        count(key, "sqlite_only")
        conflicts["sqlite_only_active" if bool(row["is_active"]) else "sqlite_only_inactive"] += 1
        if str(row["opportunity_id"]) in pg_op_ids:
            conflicts["insert_opportunity_id_collision_review"] += 1
            count(key, "insert_opportunity_id_collision_review", details={"opportunity_id": str(row["opportunity_id"])})
    for key in only_right:
        count(key, "postgres_only_preserved")
        conflicts["postgres_only_active" if bool(right[key]["is_active"]) else "postgres_only_inactive"] += 1

    for key in shared:
        a, b = left[key], right[key]
        if str(a["opportunity_id"]) != str(b["opportunity_id"]):
            conflicts["association_id_mismatch"] += 1
            count(key, "association_id_mismatch", details={"sqlite_opportunity_id": str(a["opportunity_id"]), "postgres_opportunity_id": str(b["opportunity_id"])})
        if str(a["raw_hash"] or "") != str(b["raw_hash"] or ""):
            conflicts["raw_hash_mismatch"] += 1
            count(key, "raw_hash_mismatch")
            sa, sb = _time(a["last_changed_at"]), _time(b["last_changed_at"])
            if sa is None or sb is None:
                newer["unknown_content_recency"] += 1
            elif sa > sb:
                newer["sqlite_content_timestamp_newer"] += 1
            elif sb > sa:
                newer["postgres_content_timestamp_newer"] += 1
            else:
                newer["equal_content_timestamps"] += 1
        if str(a["processing_version"] or "") != str(b["processing_version"] or ""):
            conflicts["processing_version_mismatch"] += 1
            count(key, "processing_version_mismatch")
        status_diff = bool(a["is_active"]) != bool(b["is_active"])
        lifecycle_diff = (status_diff or int(a["miss_count"] or 0) != int(b["miss_count"] or 0)
                          or _time(a["missing_since"]) != _time(b["missing_since"])
                          or _time(a["inactive_at"]) != _time(b["inactive_at"]))
        if status_diff:
            conflicts["active_status_mismatch"] += 1
            count(key, "active_status_mismatch", details={"sqlite_active": bool(a["is_active"]), "postgres_active": bool(b["is_active"])})
        if lifecycle_diff:
            conflicts["lifecycle_review"] += 1
            count(key, "lifecycle_review")
        if (str(a["opportunity_id"]) == str(b["opportunity_id"])
                and str(a["raw_hash"] or "") == str(b["raw_hash"] or "")
                and str(a["processing_version"] or "") == str(b["processing_version"] or "")
                and not lifecycle_diff):
            conflicts["matching_core_state"] += 1
            count(key, "matching_core_state")
        seen_a, seen_b = _time(a["last_seen_at"]), _time(b["last_seen_at"])
        if seen_a is not None and seen_b is not None:
            if seen_a > seen_b:
                newer["sqlite_seen_newer"] += 1
            elif seen_b > seen_a:
                newer["postgres_seen_newer"] += 1
            else:
                newer["seen_timestamps_equal"] += 1

    s_scores, p_scores = _rel_scores(sqlite_scores), _rel_scores(postgres_scores)
    s_intents, p_intents = _rel_intents(sqlite_intents), _rel_intents(postgres_intents)
    expected_s = _payload_scores(sqlite_payloads, left) if sqlite_payloads is not None else None
    expected_p = _payload_scores(postgres_payloads, right) if postgres_payloads is not None else None
    shared_ids = sorted(sqlite_op_ids & pg_op_ids)
    derived: Counter[str] = Counter()
    for opportunity_id in shared_ids:
        scores_a, scores_b = s_scores.get(opportunity_id, {}), p_scores.get(opportunity_id, {})
        if scores_a != scores_b:
            derived["course_scores_mismatch"] += 1
            if len(samples["course_scores_mismatch"]) < max_samples:
                item: dict[str, Any] = {"opportunity_id": opportunity_id, "sqlite_courses": len(scores_a), "postgres_courses": len(scores_b)}
                if expected_s is not None and expected_p is not None:
                    item["sqlite_matches_payload"] = scores_a == expected_s.get(opportunity_id, {})
                    item["postgres_matches_payload"] = scores_b == expected_p.get(opportunity_id, {})
                samples["course_scores_mismatch"].append(item)
        if s_intents.get(opportunity_id, set()) != p_intents.get(opportunity_id, set()):
            derived["intents_mismatch"] += 1
        if expected_s is not None and scores_a != expected_s.get(opportunity_id, {}):
            derived["sqlite_scores_vs_payload_mismatch"] += 1
        if expected_p is not None and scores_b != expected_p.get(opportunity_id, {}):
            derived["postgres_scores_vs_payload_mismatch"] += 1

    return {
        "read_only": True,
        "apply_supported": False,
        "safe_automatic_updates": 0,
        "policy": "Preserve PostgreSQL-only records; SQLite-only are insert candidates, not authorized writes. Never resolve hashes, lifecycle, scores, intents or associations by timestamp alone.",
        "postings": {
            "sqlite": len(left), "postgres": len(right), "shared": len(shared),
            "sqlite_only_insert_candidates": len(only_left),
            "postgres_only_preserve": len(only_right),
            "union_if_preserved": len(keys_left | keys_right),
        },
        "shared_opportunity_ids": len(shared_ids),
        "shared_posting_conflicts": dict(sorted(conflicts.items())),
        "timestamp_evidence_not_authority": dict(sorted(newer.items())),
        "derived_differences": dict(sorted(derived.items())),
        "by_source": {k: dict(sorted(v.items())) for k, v in sorted(per_source.items())},
        "samples": {k: v for k, v in sorted(samples.items())},
        "next_step": "Review source collection coverage and classification provenance, then design a separately guarded transactional apply with backup and rollback.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Snapshot SQLite (read-only).")
    parser.add_argument("--output", type=Path, help="Optional local JSON report, never a database write.")
    parser.add_argument("--max-samples", type=int, default=5)
    args = parser.parse_args()
    if args.max_samples < 1:
        parser.error("--max-samples deve ser >= 1")
    if not args.db.is_file():
        parser.error(f"Snapshot nao encontrado: {args.db}")
    if not os.getenv("DATABASE_URL", "").strip():
        parser.error("DATABASE_URL nao configurada")

    from storage.postgres_repository import PostgresOpportunityRepository

    sqlite_uri = args.db.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(sqlite_uri, uri=True) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        local_postings = con.execute(POSTINGS_SQL).fetchall()
        local_scores = con.execute(SCORES_SQL).fetchall()
        local_intents = con.execute(INTENTS_SQL).fetchall()
        local_payloads = con.execute(SQLITE_PAYLOAD_SQL).fetchall()

    with PostgresOpportunityRepository() as repo:
        repo.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        repo.conn.execute("SET TRANSACTION READ ONLY")
        remote_postings = repo.conn.execute(POSTINGS_SQL.replace("FROM source_postings", "FROM public.source_postings")).fetchall()
        remote_scores = repo.conn.execute(SCORES_SQL.replace("FROM opportunity_course_scores", "FROM public.opportunity_course_scores")).fetchall()
        remote_intents = repo.conn.execute(INTENTS_SQL.replace("FROM opportunity_intents", "FROM public.opportunity_intents")).fetchall()
        remote_payloads = repo.conn.execute(POSTGRES_PAYLOAD_SQL).fetchall()
        repo.conn.rollback()

    report = build_reconciliation_plan(
        local_postings, remote_postings,
        sqlite_scores=local_scores, postgres_scores=remote_scores,
        sqlite_intents=local_intents, postgres_intents=remote_intents,
        sqlite_payloads=local_payloads, postgres_payloads=remote_payloads,
        max_samples=args.max_samples,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Relatorio salvo em: {args.output}")
    print(rendered)
    print("CP5: planejamento somente leitura, nenhum banco alterado.")


if __name__ == "__main__":
    main()
