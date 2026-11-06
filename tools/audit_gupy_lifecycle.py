"""Audit Gupy availability using explicit job-page closure notices.

Usage from repository root, with Spring Boot stopped:
    python -m tools.audit_gupy_lifecycle --db web-mvc/radar-web.db --apply --limit 500

Without --apply, runs a preview and leaves lifecycle unchanged.
This tool never assumes 404, timeout, CAPTCHA or missing search results = closed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from processing.gupy_lifecycle import gupy_job_id, select_url_candidates
from storage.sqlite_repository import SQLiteOpportunityRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/classroom_latest.db"))
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--url", action="append", default=[],
                        help="Verifica uma vaga especifica da Gupy (repetivel); "
                             "usa o ID dentro do link /job/Base64 ou /jobs/123")
    parser.add_argument("--confirm-closed-url", action="append", default=[],
                        help="Marcar como encerrada uma URL que VOCE verificou como fechada "
                             "(repetivel; requer --apply).")
    parser.add_argument("--apply", action="store_true",
                        help="Inactivate only jobs with confirmed closed status")
    args = parser.parse_args()

    path = args.db.expanduser().resolve()
    if not path.is_file():
        parser.error(f"SQLite nao encontrado: {path}")
    if not 0 <= args.limit <= 2000 or not 1 <= args.workers <= 12:
        parser.error("Use --limit entre 0 e 2000 e --workers entre 1 e 12")

    if args.confirm_closed_url and not args.apply:
        parser.error("--confirm-closed-url requer --apply (confirmacao explicita).")
    if args.confirm_closed_url and args.url:
        parser.error("Use --url OU --confirm-closed-url; nao misture os modos.")
    for raw in args.url + args.confirm_closed_url:
        if gupy_job_id(raw) is None:
            parser.error(f"Link Gupy nao reconhecido: {raw}")
    print(f"[GUPY] SQLite: {path}")
    print("[GUPY] Modo: aplicar mudancas" if args.apply else
          "[GUPY] Previa sem aplicar (adicione --apply para atualizar)")
    with SQLiteOpportunityRepository(path) as repository:
        conn = repository._store.conn
        before = {
            "total": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            "active": conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active=1").fetchone()[0],
            "gupy_active": conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_active=1 AND source LIKE 'gupy_%'"
            ).fetchone()[0],
        }
        print("[ANTES] "
              f"{before['total']} anuncios guardados | "
              f"{before['active']} ativos de todas as fontes | "
              f"{before['gupy_active']} Gupy ativos")
        if args.apply:
            backup_dir = path.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = backup_dir / f"{path.stem}-before-gupy-audit-{timestamp}.db"
            # SQLite backup API correctly handles WAL files and concurrent readers.
            with sqlite3.connect(backup_path) as backup:
                repository._store.conn.backup(backup)
            print(f"[BACKUP] {backup_path}")

        if args.confirm_closed_url:
            candidates, unmatched = select_url_candidates(conn, args.confirm_closed_url)
            if unmatched:
                print("[GUPY] IDs nao encontrados neste banco ativo: " + ", ".join(unmatched))
            keys = {(source, job_id) for source, job_id, _ in candidates}
            changed = repository.mark_gupy_closed(keys)
            repository.commit()
            print("[GUPY] Encerramento manual confirmado pelo usuario; "
                  f"{len(keys)} anuncios localizados.")
            stats = {"checked": len(keys), "closed": len(keys),
                     "unknown": 0, "inactivated": changed}
        else:
            stats = repository.audit_gupy(
                limit=args.limit, workers=args.workers, apply=args.apply,
                urls=args.url
            )
        if args.apply and stats["inactivated"] > 0:
            repository.sync_unified_schema()
        print(
            f'[GUPY] {stats["checked"]} links | {stats["closed"]} encerradas '
            f'confirmadas | {stats["unknown"]} inconclusivas | '
            f'{stats["inactivated"]} marcadas inativas.'
        )
        if args.apply:
            after = {
                "total": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "active": conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active=1").fetchone()[0],
                "gupy_active": conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE is_active=1 AND source LIKE 'gupy_%'"
                ).fetchone()[0],
            }
            print("[DEPOIS] "
                  f"{after['total']} anuncios guardados | "
                  f"{after['active']} ativos de todas as fontes | "
                  f"{after['gupy_active']} Gupy ativos")
            print("[OK] Nenhuma vaga apagada. Contas e favoritos preservados.")
        else:
            print("[PREVIA] Nenhuma vaga foi inativada. Use --apply para efetivar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
