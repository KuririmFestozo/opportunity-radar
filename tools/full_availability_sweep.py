"""Parallel, lossless availability sweep of every active posting in every source.

Runner-local tasks:
  restore --archive FILE --metadata FILE --db FILE
  shard --db FILE --shards 12 --shard 0 --output DIR --workers 4
  merge --db FILE --results DIR --shards 12 --summary FILE
  pack --db FILE --metadata FILE --summary FILE --output DIR

The shard jobs only write compact verdict JSONL and never modify the database.
The merge job checks that every active source posting was examined exactly
once, then updates verification status transactionally. HTTP errors, redirects,
logins and unsafe links remain unverified; only evidence-backed 'closed'
can make a posting inactive. No historical posting is deleted.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from processing.source_availability import (
    apply_result, ensure_schema, probe, source_coverage,
)


class SweepError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shard_number(source: str, source_job_id: str, shards: int) -> int:
    key = (source + "\0" + source_job_id).encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % shards


def _connect(db: Path, read_only: bool = False) -> sqlite3.Connection:
    if not db.is_file():
        raise SweepError(f"Arquivo SQLite ausente: {db}")
    if read_only:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db, timeout=45)
    conn.execute("PRAGMA busy_timeout=45000")
    return conn


def _check_db(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise SweepError("SQLite falhou em PRAGMA quick_check")
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if not {"opportunities", "source_postings", "jobs"} <= tables:
        raise SweepError("Arquivo incompleto: faltam tabelas do catalogo")


def restore(archive: Path, metadata_path: Path, db: Path) -> None:
    """Restore the main channel release with strict SHA-256 checking."""
    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    if meta.get("channel") != "main":
        raise SweepError("O snapshot nao pertence ao canal main")
    if not all(isinstance(meta.get(k), str) and len(meta[k]) == 64
               for k in ("db_sha256", "gzip_sha256")):
        raise SweepError("Metadata do snapshot sem hashes completos")
    if sha256(archive) != meta["gzip_sha256"]:
        raise SweepError("Checksum do gzip do release nao corresponde")
    db.parent.mkdir(parents=True, exist_ok=True)
    # A temporary file prevents corrupt downloads overwriting the cache.
    with tempfile.NamedTemporaryFile(
        dir=db.parent, prefix="full-audit-", suffix=".db", delete=False
    ) as target:
        tmp = Path(target.name)
        try:
            with gzip.open(archive, "rb") as source:
                shutil.copyfileobj(source, target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    try:
        if sha256(tmp) != meta["db_sha256"]:
            raise SweepError("Checksum do SQLite do release nao corresponde")
        if isinstance(meta.get("db_bytes"), int) and tmp.stat().st_size != meta["db_bytes"]:
            raise SweepError("O tamanho do SQLite nao corresponde ao release")
        with _connect(tmp, read_only=True) as conn:
            _check_db(conn)
        os.replace(tmp, db)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"[RESTORE] main snapshot SHA-256 {meta['db_sha256'][:16]}...")


def _all_active(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT source,source_job_id,url FROM source_postings "
        "WHERE is_active=1 ORDER BY source,source_job_id"
    )


def _safe_probe(source: str, url: str) -> tuple[str, str]:
    try:
        verdict, evidence = probe(source, url)
        if verdict not in {"open", "closed", "unverified"}:
            return "unverified", "invalid_verdict"
        evidence = str(evidence or "")[:250]
        return verdict, evidence
    except Exception:
        # A failure never proves that a posting has closed.
        return "unverified", "probe_exception"


def scan_shard(db: Path, *, shard: int, shards: int, out: Path,
               workers: int = 4) -> dict:
    if shards < 1 or not 0 <= shard < shards:
        raise SweepError("Indice de shard fora do intervalo")
    if not 1 <= workers <= 6:
        raise SweepError("Limite de 1 a 6 workers por shard")
    out.mkdir(parents=True, exist_ok=True)
    db_hash = sha256(db)
    with _connect(db, read_only=True) as conn:
        _check_db(conn)
        jobs = [
            (str(source), str(job_id), str(url or ""))
            for source, job_id, url in _all_active(conn)
            if shard_number(str(source), str(job_id), shards) == shard
        ]
    total = len(jobs)
    print(f"[SHARD {shard}/{shards}] {total} anuncios ativos para verificar", flush=True)
    output = out / "verdicts.jsonl"
    counts = Counter()
    by_source = defaultdict(Counter)
    stamp = datetime.now(timezone.utc).isoformat()
    with output.open("w", encoding="utf-8") as stream, ThreadPoolExecutor(
        max_workers=workers
    ) as executor:
        pending = {
            executor.submit(_safe_probe, source, url): (source, job_id)
            for source, job_id, url in jobs
        }
        for future in as_completed(pending):
            source, job_id = pending[future]
            verdict, evidence = future.result()
            stream.write(json.dumps({
                "source": source, "source_job_id": job_id, "verdict": verdict,
                "evidence": evidence, "checked_at": stamp,
            }, ensure_ascii=False) + "\n")
            counts[verdict] += 1
            by_source[source][verdict] += 1
            checked = sum(counts.values())
            if checked % 250 == 0 or checked == total:
                stream.flush()
                print(f"[SHARD {shard}] {checked}/{total}: "
                      f"{counts['open']} abertas, {counts['closed']} encerradas, "
                      f"{counts['unverified']} inconclusivas", flush=True)
    manifest = {
        "shard": shard, "shards": shards, "snapshot_sha256": db_hash,
        "expected": total, "checked": sum(counts.values()),
        "counts": dict(counts),
        "by_source": {src: dict(v) for src, v in sorted(by_source.items())},
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def merge_shards(db: Path, *, results: Path, shards: int, summary_path: Path) -> dict:
    """Require complete coverage and unchanged database before any UPDATE."""
    db_hash = sha256(db)
    with _connect(db) as conn:
        _check_db(conn)
        expected = {(str(source), str(job_id)) for source, job_id, _ in _all_active(conn)}
        personal = [
            t for t in ("web_users", "web_device_favorites",
                        "web_device_applications", "web_favorites", "web_applications")
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
        ]
        counts_before = {
            name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for name in personal
        }
        total_history = conn.execute("SELECT count(*) FROM source_postings").fetchone()[0]
        actual = set()
        updates = []
        for shard in range(shards):
            folder = results / f"availability-shard-{shard}"
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            if (manifest["shard"] != shard or manifest["shards"] != shards
                    or manifest["snapshot_sha256"] != db_hash):
                raise SweepError(f"Shard {shard} tem metadata de outro snapshot")
            found = 0
            with (folder / "verdicts.jsonl").open(encoding="utf-8") as stream:
                for line in stream:
                    item = json.loads(line)
                    source, job_id = str(item["source"]), str(item["source_job_id"])
                    key = (source, job_id)
                    if (key in actual or key not in expected
                            or shard_number(source, job_id, shards) != shard):
                        raise SweepError(f"Shard {shard} contem chave repetida/invalida: {key}")
                    if item["verdict"] not in ("open", "closed", "unverified"):
                        raise SweepError("Veredito invalido no lote")
                    if not str(item["checked_at"]).endswith("+00:00"):
                        raise SweepError("Data de verificacao invalida")
                    actual.add(key)
                    updates.append(item)
                    found += 1
            if found != manifest["expected"] or found != manifest["checked"]:
                raise SweepError(f"Shard {shard} incompleto: {found} vereditos")
        if actual != expected:
            raise SweepError(
                f"Auditoria incompleta: {len(actual)} de {len(expected)} "
                f"(faltam {len(expected - actual)})")
        print(f"[MERGE] Cobertura completa: {len(actual)} de {len(expected)} anúncios ativos")
        # Read all data first, begin a transaction only after validation.
        conn.execute("BEGIN IMMEDIATE")
        ensure_schema(conn)
        counts = Counter()
        by_source = defaultdict(Counter)
        reasons = Counter()
        deactivated = 0
        for item in updates:
            source, job_id = item["source"], item["source_job_id"]
            verdict, evidence = item["verdict"], item["evidence"]
            deactivated += apply_result(
                conn, source, job_id, verdict, evidence,
                checked_at=item["checked_at"],
            )
            counts[verdict] += 1
            by_source[source][verdict] += 1
            reasons[evidence] += 1
        if conn.execute("SELECT count(*) FROM source_postings").fetchone()[0] != total_history:
            conn.rollback()
            raise SweepError("A auditoria nao pode excluir nenhum anuncio historico")
        if any(conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] != c
               for t, c in counts_before.items()):
            conn.rollback()
            raise SweepError("Contas e favoritos mudaram durante a auditoria")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            conn.rollback()
            raise SweepError("Integridade referencial invalida")
        conn.commit()
        coverage = source_coverage(conn)
        remaining = conn.execute(
            "SELECT count(*) FROM source_postings WHERE is_active=1"
        ).fetchone()[0]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_sha256": db_hash,
        "source_families": len(by_source),
        "historical_postings": total_history,
        "examined_active_postings": len(expected),
        "verified_open": counts["open"],
        "verified_closed": counts["closed"],
        "unverified": counts["unverified"],
        "deactivated": deactivated,
        "active_postings_after": remaining,
        "by_source": {src: dict(v) for src, v in sorted(by_source.items())},
        "reasons": dict(reasons),
        "coverage": coverage,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[DONE] {len(expected)} vagas verificadas; "
          f"{counts['closed']} encerramentos confirmados; "
          f"{deactivated} desativadas; {counts['unverified']} inconclusivas")
    return summary


def pack(db: Path, original_meta: Path, summary: Path, output: Path) -> None:
    """Package an updated main release, preserving the existing dashboard checksum."""
    output.mkdir(parents=True, exist_ok=True)
    with _connect(db, read_only=True) as conn:
        _check_db(conn)
    old = json.loads(original_meta.read_text(encoding="utf-8"))
    if old.get("channel") != "main":
        raise SweepError("Metadata de origem nao pertence a main")
    report = json.loads(summary.read_text(encoding="utf-8"))
    archived = output / "opportunity_radar-main.db.gz"
    with archived.open("wb") as dest:
        with gzip.GzipFile(filename="", mode="wb", fileobj=dest, mtime=0) as gz:
            with db.open("rb") as inp:
                shutil.copyfileobj(inp, gz)
    updated = dict(old)
    updated.update({
        "commit_sha": os.environ.get("GITHUB_SHA", old.get("commit_sha")),
        "run_id": os.environ.get("GITHUB_RUN_ID", old.get("run_id")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_bytes": db.stat().st_size,
        "db_sha256": sha256(db),
        "gzip_sha256": sha256(archived),
        "availability_full_audit": {
            "examined": report["examined_active_postings"],
            "closed": report["verified_closed"],
            "unverified": report["unverified"],
            "deactivated": report["deactivated"],
        },
    })
    (output / "opportunity_radar-main.state.json").write_text(
        json.dumps(updated, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PACK] {archived.stat().st_size} bytes gzip, SHA-256 validado")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    restore_p = sub.add_parser("restore")
    restore_p.add_argument("--archive", type=Path, required=True)
    restore_p.add_argument("--metadata", type=Path, required=True)
    restore_p.add_argument("--db", type=Path, required=True)
    shard_p = sub.add_parser("shard")
    shard_p.add_argument("--db", type=Path, required=True)
    shard_p.add_argument("--shard", type=int, required=True)
    shard_p.add_argument("--shards", type=int, default=12)
    shard_p.add_argument("--workers", type=int, default=4)
    shard_p.add_argument("--output", type=Path, required=True)
    merge_p = sub.add_parser("merge")
    merge_p.add_argument("--db", type=Path, required=True)
    merge_p.add_argument("--results", type=Path, required=True)
    merge_p.add_argument("--shards", type=int, default=12)
    merge_p.add_argument("--summary", type=Path, required=True)
    pack_p = sub.add_parser("pack")
    pack_p.add_argument("--db", type=Path, required=True)
    pack_p.add_argument("--metadata", type=Path, required=True)
    pack_p.add_argument("--summary", type=Path, required=True)
    pack_p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        if args.cmd == "restore":
            restore(args.archive, args.metadata, args.db)
        elif args.cmd == "shard":
            scan_shard(args.db, shard=args.shard, shards=args.shards,
                       workers=args.workers, out=args.output)
        elif args.cmd == "merge":
            merge_shards(args.db, results=args.results, shards=args.shards,
                         summary_path=args.summary)
        elif args.cmd == "pack":
            pack(args.db, args.metadata, args.summary, args.output)
    except (OSError, ValueError, KeyError, sqlite3.Error, SweepError) as error:
        p.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
