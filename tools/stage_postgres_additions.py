"""CP5 staged additive sync: preserves existing PostgreSQL rows.

Default is PREVIEW ONLY. A future explicit --apply requires a verified pg_dump
backup, immutable source fingerprint and live destination guard. This is NOT a
general conflict resolver, lifecycle reconciliation or PostgreSQL cutover.

Example (preview):
  python -m tools.stage_postgres_additions --db data/snapshots/main-20261010.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

POSTING_ID_SQL = """
SELECT source, source_job_id, opportunity_id, association_method, raw_hash,
       processing_version, is_active, miss_count, last_changed_at
FROM source_postings
"""
TABLES = ("opportunities", "source_postings", "opportunity_course_scores",
          "opportunity_intents", "discovery_state", "collection_scopes")
TRANSFER_TABLES = TABLES[:5]


def _rows_by_key(rows: Iterable[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for raw in rows:
        row = dict(raw)
        key = (str(row["source"]), str(row["source_job_id"]))
        if key in result or not all(key):
            raise ValueError(f"Invalid or duplicate source identity: {key!r}")
        result[key] = row
    return result


def _digest_remote(postings: dict[tuple[str, str], dict[str, Any]],
                   opportunity_ids: set[str]) -> str:
    """Guard target identity and state, not merely target row counts."""
    sha = hashlib.sha256()
    for key in sorted(postings):
        row = postings[key]
        record = [
            key[0], key[1], str(row["opportunity_id"]),
            str(row.get("association_method") or "identity"),
            str(row["raw_hash"]), str(row["processing_version"]),
            bool(row["is_active"]), int(row["miss_count"] or 0),
            str(row["last_changed_at"]),
        ]
        sha.update(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode())
        sha.update(b"\n")
    for opportunity_id in sorted(opportunity_ids):
        sha.update(b"O" + opportunity_id.encode() + b"\n")
    return sha.hexdigest()


def plan_additions(
    local_rows: Iterable[Any],
    remote_rows: Iterable[Any],
    remote_opportunity_ids: Iterable[str],
    *,
    max_samples: int = 5,
) -> dict[str, Any]:
    """Do not insert associated postings or any row with an existing target UUID."""
    if max_samples < 1:
        raise ValueError("max_samples must be >= 1")
    local, remote = _rows_by_key(local_rows), _rows_by_key(remote_rows)
    existing_ids = {str(value) for value in remote_opportunity_ids}
    by_op_id: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, row in local.items():
        by_op_id[str(row["opportunity_id"])].append(key)

    safe: list[tuple[str, str]] = []
    blocked: Counter[str] = Counter()
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    samples: list[dict[str, str]] = []
    for key in sorted(set(local) - set(remote)):
        row = local[key]
        op_id = str(row["opportunity_id"])
        if op_id in existing_ids:
            reason = "opportunity_id_already_in_postgres"
        elif len(by_op_id[op_id]) != 1:
            reason = "sqlite_cross_source_association"
        elif str(row.get("association_method") or "identity") != "identity":
            reason = "non_identity_association"
        else:
            reason = None
        if reason:
            blocked[reason] += 1
            by_source[key[0]]["blocked"] += 1
            if len(samples) < max_samples:
                samples.append({"source": key[0], "source_job_id": key[1], "reason": reason})
        else:
            safe.append(key)
            by_source[key[0]]["candidate"] += 1

    remote_digest = _digest_remote(remote, existing_ids)
    return {
        "read_only": True,
        "apply_supported": True,
        "apply_executed": False,
        "scope": "additive_new_independent_opportunities_only",
        "sqlite_postings": len(local),
        "postgres_postings": len(remote),
        "postgres_opportunities": len(existing_ids),
        "shared_postings_untouched": len(set(local) & set(remote)),
        "postgres_only_postings_untouched": len(set(remote) - set(local)),
        "sqlite_only_postings": len(set(local) - set(remote)),
        "candidate_insert_count": len(safe),
        "candidate_active": sum(bool(local[key]["is_active"]) for key in safe),
        "candidate_inactive": sum(not bool(local[key]["is_active"]) for key in safe),
        "blocked_insert_count": sum(blocked.values()),
        "blocked_by_reason": dict(sorted(blocked.items())),
        "blocked_samples": samples,
        "by_source": {k: dict(sorted(v.items())) for k, v in sorted(by_source.items())},
        "postgres_fingerprint": remote_digest,
        "candidate_source_keys": safe,  # omitted from human-facing JSON output
        "preservation": "No UPDATE, DELETE, TRUNCATE, or existing opportunity changes. Only add new, independent opportunities and their dependent rows.",
        "excluded": ["shared posting changes", "lifecycle transitions on existing postings",
                     "scores/intents on existing opportunities", "collection_scopes updates"],
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise RuntimeError(f"Snapshot absent: {path}")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        conn.close()
        raise RuntimeError("SQLite failed quick_check")
    if conn.execute("PRAGMA foreign_key_check").fetchone():
        conn.close()
        raise RuntimeError("SQLite failed foreign_key_check")
    return conn


def _target_snapshot(conn: Any) -> tuple[list[Any], set[str]]:
    rows = conn.execute(
        POSTING_ID_SQL.replace("FROM source_postings", "FROM public.source_postings")
    ).fetchall()
    ids = {str(r["id"]) for r in conn.execute("SELECT id FROM public.opportunities")}
    return rows, ids


def _load_rows(conn: sqlite3.Connection, table: str, field: str, keys: list[Any]) -> list[dict[str, Any]]:
    """Chunked SQLite IN lookups; all source values come from read-only snapshot."""
    if table not in TRANSFER_TABLES:
        raise ValueError("Unknown transfer table")
    result = []
    for index in range(0, len(keys), 300):
        subset = keys[index:index + 300]
        if not subset:
            continue
        placeholders = ",".join("?" for _ in subset)
        sql = f"SELECT * FROM {table} WHERE {field} IN ({placeholders})"
        result.extend(dict(row) for row in conn.execute(sql, subset))
    return result


def _collect_inserts(
    conn: sqlite3.Connection,
    eligible: list[tuple[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    """Read only eligible independent postings, never other catalog identities."""
    ids = [source_id for _, source_id in eligible]
    # Source-native job ids can repeat between sources. Filter by FULL identity.
    eligible_set = set(eligible)
    posting_rows: list[dict[str, Any]] = []
    for key_start in range(0, len(eligible), 200):
        batch = eligible[key_start:key_start + 200]
        where = " OR ".join("(source=? AND source_job_id=?)" for _ in batch)
        args = [part for key in batch for part in key]
        posting_rows.extend(dict(r) for r in conn.execute(
            f"SELECT * FROM source_postings WHERE {where}", args
        ))
    if {(r["source"], r["source_job_id"]) for r in posting_rows} != eligible_set:
        raise RuntimeError("Selected posting identities do not match snapshot")
    op_ids = [str(r["opportunity_id"]) for r in posting_rows]
    if len(op_ids) != len(set(op_ids)):
        raise RuntimeError("Additive stage cannot insert cross-source groups")

    opportunities = _load_rows(conn, "opportunities", "id", op_ids)
    scores = _load_rows(conn, "opportunity_course_scores", "opportunity_id", op_ids)
    intents = _load_rows(conn, "opportunity_intents", "opportunity_id", op_ids)
    # Discovery state can exist without a posting. Only copy actual candidate keys.
    discovered = []
    for offset in range(0, len(eligible), 200):
        batch = eligible[offset:offset + 200]
        where = " OR ".join("(source=? AND source_job_id=?)" for _ in batch)
        args = [part for key in batch for part in key]
        discovered.extend(dict(r) for r in conn.execute(
            f"SELECT * FROM discovery_state WHERE {where}", args
        ))
    if {str(r["id"]) for r in opportunities} != set(op_ids):
        raise RuntimeError("Missing opportunities in SQLite snapshot")
    if len(discovered) != len({(r["source"], r["source_job_id"]) for r in discovered}):
        raise RuntimeError("Duplicate discovery identities in SQLite")
    return {
        "opportunities": opportunities,
        "source_postings": posting_rows,
        "opportunity_course_scores": scores,
        "opportunity_intents": intents,
        "discovery_state": discovered,
    }


def _backup_with_pg_dump(dsn: str, backup_dir: Path) -> dict[str, Any]:
    """Require verified public-schema logical backup BEFORE opening write transaction."""
    from psycopg.conninfo import conninfo_to_dict

    if shutil.which("pg_dump") is None or shutil.which("pg_restore") is None:
        raise RuntimeError("pg_dump and pg_restore are required for --apply (matching server major version)")
    params = conninfo_to_dict(dsn)
    env = os.environ.copy()
    for opt, var in (
        ("host", "PGHOST"), ("hostaddr", "PGHOSTADDR"), ("port", "PGPORT"),
        ("user", "PGUSER"), ("password", "PGPASSWORD"), ("dbname", "PGDATABASE"),
        ("sslmode", "PGSSLMODE"),
    ):
        if params.get(opt):
            env[var] = str(params[opt])
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = backup_dir / f"cp5-preadditive-{stamp}.dump"
    result = subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-acl",
         "--schema=public", "--file", str(path)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        timeout=1800, check=False,
    )
    if result.returncode != 0:
        path.unlink(missing_ok=True)
        raise RuntimeError("PostgreSQL backup failed. Check pg_dump/server compatibility and connection.")
    if not path.exists() or path.stat().st_size < 1024:
        raise RuntimeError("PostgreSQL backup is absent or suspiciously small")
    verify = subprocess.run(
        ["pg_restore", "--list", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
    )
    if verify.returncode != 0 or any(
        f"TABLE DATA public {table} " not in verify.stdout for table in TABLES
    ):
        raise RuntimeError("Backup catalog verification failed; apply forbidden")
    return {"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}


def _run_additive(
    sqlite_conn: sqlite3.Connection, repo: Any,
    plan: dict[str, Any], *,
    expected_source_sha256: str, snapshot_sha256: str,
    expected_postgres_fingerprint: str, expected_inserts: int,
) -> dict[str, Any]:
    """One transaction. On any mismatch/exception the caller rolls back."""
    if snapshot_sha256 != expected_source_sha256:
        raise RuntimeError("SQLite snapshot hash no longer matches preview")
    if plan["postgres_fingerprint"] != expected_postgres_fingerprint:
        raise RuntimeError("PostgreSQL fingerprint no longer matches preview")
    if plan["candidate_insert_count"] != expected_inserts:
        raise RuntimeError("Candidate count changed after preview")
    if plan["blocked_insert_count"]:
        # Allowed: blocking collisions are SKIPPED, never overwritten.
        pass

    from tools.migrate_sqlite_to_postgres import (
        _migrate_course_scores, _migrate_discovery, _migrate_intents,
        _migrate_opportunities, _migrate_source_postings,
    )
    rows = _collect_inserts(sqlite_conn, plan["candidate_source_keys"])
    pg = repo.conn
    # Do not overwrite even pre-existing discovery records of missing postings.
    discovered_keys = {(r["source"], r["source_job_id"]) for r in rows["discovery_state"]}
    for offset in range(0, len(discovered_keys), 200):
        chunk = sorted(discovered_keys)[offset:offset + 200]
        already = pg.execute(
            "SELECT source, source_job_id FROM public.discovery_state "
            "WHERE (source, source_job_id) IN ("
            + ",".join(["(%s,%s)"] * len(chunk)) + ")",
            [component for key in chunk for component in key],
        ).fetchall()
        if already:
            raise RuntimeError("Existing PostgreSQL discovery state collides with additive candidate")

    before = {table: int(pg.execute(f"SELECT COUNT(*) AS n FROM public.{table}").fetchone()["n"])
              for table in TRANSFER_TABLES}
    for table, fn in (
        ("opportunities", _migrate_opportunities),
        ("source_postings", _migrate_source_postings),
        ("opportunity_course_scores", _migrate_course_scores),
        ("opportunity_intents", _migrate_intents),
        ("discovery_state", _migrate_discovery),
    ):
        fn(pg, rows[table])
    after = {table: int(pg.execute(f"SELECT COUNT(*) AS n FROM public.{table}").fetchone()["n"])
             for table in TRANSFER_TABLES}
    for table in TRANSFER_TABLES:
        if after[table] - before[table] != len(rows[table]):
            raise RuntimeError(f"Unexpected table changes in {table}: rollback required")
    return {"inserted": {name: len(entries) for name, entries in rows.items()},
            "counts_before": before, "counts_after": after}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--output", type=Path, help="Write preview JSON only")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--expected-source-sha256")
    p.add_argument("--expected-postgres-fingerprint")
    p.add_argument("--expected-inserts", type=int)
    p.add_argument("--confirm-additive-only", action="store_true")
    p.add_argument("--backup-dir", type=Path, default=Path("data/backups/postgres"))
    args = p.parse_args()

    if not os.getenv("DATABASE_URL", "").strip():
        p.error("DATABASE_URL not configured")
    from storage.postgres_repository import PostgresOpportunityRepository
    sqlite_conn = _sqlite_connect(args.db)
    try:
        source_sha = _sha256(args.db)
        with PostgresOpportunityRepository() as repo:
            pg = repo.conn
            pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            pg.execute("SET TRANSACTION READ ONLY")
            local = sqlite_conn.execute(POSTING_ID_SQL).fetchall()
            remote, existing_op_ids = _target_snapshot(pg)
            report = plan_additions(local, remote, existing_op_ids)
            pg.rollback()
            printable = {k: v for k, v in report.items() if k != "candidate_source_keys"}
            printable["sqlite_sha256"] = source_sha
            text = json.dumps(printable, indent=2, ensure_ascii=False) + "\n"

            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text, encoding="utf-8")
            print(text)

            if not args.apply:
                print("DRY-RUN only: no PostgreSQL changes.")
                return
            if (not args.confirm_additive_only
                    or args.expected_source_sha256 != source_sha
                    or args.expected_postgres_fingerprint != report["postgres_fingerprint"]
                    or args.expected_inserts != report["candidate_insert_count"]
                    or args.expected_inserts is None or args.expected_inserts < 1):
                raise SystemExit("Apply guards missing or outdated: no writes attempted.")

            backup = _backup_with_pg_dump(repo.dsn, args.backup_dir)
            print(f"Verified backup: {backup['path']} sha256={backup['sha256']}")
            try:
                pg.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                pg.execute("SET LOCAL lock_timeout = '20s'")
                pg.execute("SET LOCAL statement_timeout = '30min'")
                pg.execute(
                    "LOCK TABLE public.opportunities, public.source_postings, "
                    "public.opportunity_course_scores, public.opportunity_intents, "
                    "public.discovery_state IN SHARE ROW EXCLUSIVE MODE"
                )
                fresh_rows, fresh_ids = _target_snapshot(pg)
                fresh = plan_additions(local, fresh_rows, fresh_ids)
                outcome = _run_additive(
                    sqlite_conn, repo, fresh,
                    expected_source_sha256=args.expected_source_sha256,
                    snapshot_sha256=_sha256(args.db),
                    expected_postgres_fingerprint=args.expected_postgres_fingerprint,
                    expected_inserts=args.expected_inserts,
                )
                pg.commit()
            except Exception:
                pg.rollback()
                raise
            print(json.dumps({"committed": True, "backup": backup, **outcome},
                             ensure_ascii=False, indent=2))
    finally:
        sqlite_conn.close()


if __name__ == "__main__":
    main()
