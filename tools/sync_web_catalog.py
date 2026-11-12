"""Incrementally refresh web-mvc/radar-web.db from a downloaded classroom snapshot.

Preserves all existing web_* data (users, password hashes, favorites, notes).
Copies collector tables, *never replaces the destination DB*. Also carries over
confirmed closures so newer snapshots cannot re-open locally verified closures.

From project root, with Spring Boot stopped:
    python -m tools.sync_web_catalog
    python -m tools.sync_web_catalog --import-accounts

Source: data/classroom_latest.db; target: web-mvc/radar-web.db.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "classroom_latest.db"
DEFAULT_DESTINATION = ROOT / "web-mvc" / "radar-web.db"

CATALOG = ("opportunities", "source_postings",
           "opportunity_course_scores", "opportunity_intents", "jobs")
KEYS = {
    "opportunities": ("id",),
    "source_postings": ("source", "source_job_id"),
    "opportunity_course_scores": ("opportunity_id", "course_id"),
    "opportunity_intents": ("opportunity_id", "intent_id"),
    "jobs": ("source", "source_job_id"),
}
PERSONAL = ("web_users", "web_device_favorites", "web_device_applications",
            "web_favorites", "web_applications")
ACCOUNT_KEY = {
    "web_users": ("id",),
    "web_device_favorites": ("id",),
    "web_device_applications": ("id",),
    "web_favorites": ("id",),
    "web_applications": ("id",),
}


class SyncError(RuntimeError):
    pass


def table_exists(conn, table, schema="main"):
    return conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master "
        "WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def columns(conn, table, schema="main"):
    return [row[1] for row in conn.execute(
        f'PRAGMA {schema}.table_info("{table}")'
    )]


def q(name):
    return '"' + name.replace('"', '""') + '"'


def copy_upsert(conn, table, keys, *, update=True):
    src_cols = columns(conn, table, "incoming")
    dst_cols = columns(conn, table, "main")
    missing = sorted(set(src_cols) - set(dst_cols))
    if missing:
        raise SyncError(
            f"Banco do site possui schema antigo em {table}: "
            f"faltando {', '.join(missing)}. Atualize o codigo/schema primeiro."
        )
    if not all(key in src_cols for key in keys):
        raise SyncError(f"Snapshot sem chave esperada em {table}")
    all_cols = [col for col in src_cols if col in dst_cols]
    names = ",".join(q(col) for col in all_cols)
    conflict = ",".join(q(key) for key in keys)
    assign = ",".join(
        f"{q(col)}=excluded.{q(col)}" for col in all_cols if col not in keys
    )
    # WHERE 1=1 resolves SQLite's INSERT SELECT ON CONFLICT parse ambiguity.
    if update and assign:
        suffix = f" ON CONFLICT({conflict}) DO UPDATE SET {assign}"
    else:
        suffix = f" ON CONFLICT({conflict}) DO NOTHING"
    conn.execute(
        f"INSERT INTO main.{q(table)} ({names}) "
        f"SELECT {names} FROM incoming.{q(table)} WHERE 1=1" + suffix
    )


def count(conn, table, schema="main"):
    return conn.execute(f"SELECT count(*) FROM {schema}.{q(table)}").fetchone()[0]


def check_conflicts(conn):
    for table in CATALOG:
        if not table_exists(conn, table) or not table_exists(conn, table, "incoming"):
            raise SyncError(f"Tabela de catalogo ausente: {table}")
    problems = conn.execute("""
        SELECT count(*) FROM main.source_postings d
        JOIN incoming.source_postings s
          ON s.source=d.source AND s.source_job_id=d.source_job_id
        WHERE s.opportunity_id<>d.opportunity_id
    """).fetchone()[0]
    if problems:
        raise SyncError(
            f"{problems} anúncios mudaram de opportunity_id; "
            "a sincronizacao foi bloqueada para proteger favoritos."
        )


def import_accounts(conn):
    """Opt-in: import accounts created in the classroom snapshot, if no conflicts."""
    if not table_exists(conn, "web_users", "incoming"):
        return {"accounts": 0, "favorites": 0, "applications": 0}
    if not table_exists(conn, "web_users"):
        raise SyncError("O banco de destino nao contem web_users: inicie o Spring antes.")
    collisions = conn.execute("""
        SELECT count(*) FROM incoming.web_users s
        JOIN main.web_users d ON s.username=d.username
        WHERE s.id<>d.id
    """).fetchone()[0]
    identity_conflicts = conn.execute("""
        SELECT count(*) FROM incoming.web_users s
        JOIN main.web_users d ON s.id=d.id
        WHERE s.username<>d.username OR s.password_hash<>d.password_hash
    """).fetchone()[0]
    if collisions or identity_conflicts:
        raise SyncError(
            "As bases contem contas com mesmo usuario/UUID, mas senhas ou IDs "
            "diferentes. Pare; escolha qual banco deve ser a identidade principal."
        )

    prev_accounts = count(conn, "web_users")
    copy_upsert(conn, "web_users", ACCOUNT_KEY["web_users"], update=False)
    counts = {"accounts": count(conn, "web_users") - prev_accounts,
              "favorites": 0, "applications": 0}
    for table in PERSONAL[1:]:
        if not (table_exists(conn, table) and table_exists(conn, table, "incoming")):
            continue
        old = count(conn, table)
        # Keep the target copy on collisions (its owner may have newer notes).
        src_cols = columns(conn, table, "incoming")
        dst_cols = columns(conn, table)
        if set(src_cols) - set(dst_cols):
            raise SyncError(f"Schema incompatível em {table}")
        fields = ",".join(q(k) for k in src_cols)
        # A missing opportunity cannot be associated with a favorite.
        where = (" WHERE opportunity_id IN (SELECT id FROM main.opportunities)"
                 if "opportunity_id" in src_cols else " WHERE 1=1")
        conn.execute(
            f"INSERT OR IGNORE INTO main.{q(table)}({fields}) "
            f"SELECT {fields} FROM incoming.{q(table)}{where}"
        )
        name = "favorites" if "favorite" in table else "applications"
        counts[name] += count(conn, table) - old
    return counts



def merge_source_verification(conn):
    """Bring source audits from the snapshot without undoing local closures."""
    from processing.source_availability import ensure_schema as ensure_source
    from processing.gupy_lifecycle import ensure_schema as ensure_gupy
    total = 0
    for table, ensure in (
        ("source_availability_checks", ensure_source),
        ("gupy_url_checks", ensure_gupy),
    ):
        if not table_exists(conn, table, "incoming"):
            continue
        ensure(conn)
        cols = columns(conn, table, "incoming")
        if set(cols) != set(columns(conn, table)):
            raise SyncError(f"Tabela de auditoria incompatível: {table}")
        col_sql = ",".join(q(x) for x in cols)
        update_columns = [x for x in cols if x not in ("source", "source_job_id")]
        clauses = [
            f'{q(x)}=CASE WHEN main.{q(table)}.verdict="closed" '
            f'THEN main.{q(table)}.{q(x)} ELSE excluded.{q(x)} END'
            for x in update_columns
        ]
        # A confirmed closure is stronger than a subsequent timeout / 404.
        before = count(conn, table)
        conn.execute(
            f'INSERT INTO main.{q(table)}({col_sql}) '
            f'SELECT {col_sql} FROM incoming.{q(table)} WHERE 1=1 '
            f'ON CONFLICT(source,source_job_id) DO UPDATE SET '
            + ",".join(clauses)
        )
        total += count(conn, table) - before
    return total


def retain_confirmed_closures(conn):
    clauses = []
    if table_exists(conn, "gupy_url_checks"):
        clauses.append("""
          EXISTS (SELECT 1 FROM gupy_url_checks g
                  WHERE g.source=main.source_postings.source
                    AND g.source_job_id=main.source_postings.source_job_id
                    AND g.verdict='closed')
        """)
    if table_exists(conn, "source_availability_checks"):
        clauses.append("""
          EXISTS (SELECT 1 FROM source_availability_checks a
                  WHERE a.source=main.source_postings.source
                    AND a.source_job_id=main.source_postings.source_job_id
                    AND a.verdict='closed')
        """)
    if not clauses:
        return 0
    check = " OR ".join(clauses)
    conn.execute(
        "UPDATE main.source_postings SET is_active=0 WHERE is_active=1 AND (" + check + ")"
    )
    # SQLite changes() is local to the most recent UPDATE.
    affected = conn.execute("SELECT changes()").fetchone()[0]
    if table_exists(conn, "jobs"):
        job_check = check.replace("main.source_postings.", "main.jobs.")
        conn.execute(
            "UPDATE main.jobs SET is_active=0 WHERE is_active=1 AND (" + job_check + ")"
        )
    return affected


def sync_catalog(source=DEFAULT_SOURCE, destination=DEFAULT_DESTINATION,
                 *, include_accounts=False):
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if source == destination:
        raise SyncError("O arquivo de origem e destino nao pode ser o mesmo.")
    for path in (source, destination):
        if not path.is_file():
            raise SyncError(f"Banco SQLite nao encontrado: {path}")
    # Refuse a copy over the downloaded source and collector database.
    protected = {(ROOT / "data" / "opportunity_radar.db").resolve(),
                 DEFAULT_SOURCE.resolve()}
    if destination in protected:
        raise SyncError("Nao sobrescreva o snapshot nem o banco do coletor.")

    with sqlite3.connect(destination) as conn:
        conn.execute("PRAGMA busy_timeout=12000")
        # An idle WAL/SHM file may survive after a crash. It does not by
        # itself mean the app is running. Checkpoint safely; refuse only when
        # another writer prevents a complete checkpoint.
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and checkpoint[0] != 0:
            raise SyncError(
                "SQLite ainda esta em uso. Pare o Spring Boot antes do sync."
            )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=12000")
        # ATTACH does not reliably accept pathlib's file:///C:/... URI on
        # Windows (notably on drives, spaces and localized user paths).
        # Bind the native filesystem path rather than a URI. All writes in
        # this transaction explicitly target main.*; incoming is read-only
        # by convention and the original source snapshot is never replaced.
        conn.execute("ATTACH DATABASE ? AS incoming", (str(source),))
        try:
            if conn.execute("PRAGMA main.quick_check").fetchone() != ("ok",):
                raise SyncError("O SQLite do site possui problemas de integridade.")
            if conn.execute("PRAGMA incoming.quick_check").fetchone() != ("ok",):
                raise SyncError("Snapshot de origem possui problemas de integridade.")
            check_conflicts(conn)
            old_catalog = count(conn, "opportunities")
            incoming_catalog = count(conn, "opportunities", "incoming")
            # A cleaned main snapshot may legitimately be smaller than the
            # site's historical union. Allow that ONLY if the new snapshot
            # carries actual permanent-deletion tombstones.
            has_deletions = (
                table_exists(conn, "purged_postings", "incoming")
                and count(conn, "purged_postings", "incoming") > 0
            )
            if incoming_catalog == 0 or (
                incoming_catalog < old_catalog and not has_deletions
            ):
                raise SyncError(
                    f"Snapshot tem {incoming_catalog} oportunidades e o site "
                    f"{old_catalog}. Recusei um snapshot vazio/mais antigo."
                )
            if not table_exists(conn, "web_users"):
                raise SyncError(
                    "Schema de contas ausente no SQLite do site. Inicie o Spring "
                    "uma vez apontando para radar-web.db antes de sincronizar."
                )
            personal_before = {table: count(conn, table) for table in PERSONAL
                               if table_exists(conn, table)}
            backup_dir = destination.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = backup_dir / f"{destination.stem}-before-catalog-sync-{stamp}.db"
            with sqlite3.connect(backup_path) as saved:
                conn.backup(saved)

            try:
                conn.execute("BEGIN IMMEDIATE")
                copy_upsert(conn, "opportunities", KEYS["opportunities"])
                copy_upsert(conn, "source_postings", KEYS["source_postings"])
                copy_upsert(conn, "jobs", KEYS["jobs"])
                for table in ("opportunity_course_scores", "opportunity_intents"):
                    conn.execute(
                        f"DELETE FROM main.{table} "
                        "WHERE opportunity_id IN "
                        "(SELECT id FROM incoming.opportunities)"
                    )
                    copy_upsert(conn, table, KEYS[table], update=False)

                accounts = import_accounts(conn) if include_accounts else None
                verification_imported = merge_source_verification(conn)
                protected = retain_confirmed_closures(conn)
                from processing.retirement import import_tombstones
                retirement_tombstones = import_tombstones(conn)
                personal_after = {table: count(conn, table) for table in personal_before}
                if not include_accounts and personal_after != personal_before:
                    raise SyncError("Contagem de dados pessoais alterou durante sincronizacao.")
                if conn.execute("PRAGMA main.foreign_key_check").fetchone() is not None:
                    raise SyncError("Integridade de FKs violada; revertendo a sincronizacao.")
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            result = {
                "previous_opportunities": old_catalog,
                "opportunities": count(conn, "opportunities"),
                "active_postings": conn.execute(
                    "SELECT count(*) FROM source_postings WHERE is_active=1"
                ).fetchone()[0],
                "users": count(conn, "web_users"),
                "confirmed_closures_preserved": protected,
                "accounts_imported": accounts,
                "verification_imported": verification_imported,
                "retirement_tombstones": retirement_tombstones,
                "backup": str(backup_path),
            }
            print("[OK] Catalogo atualizado no banco principal do site.")
            print(f"[VAGAS] {old_catalog} -> {result['opportunities']} historicas; "
                  f"{result['active_postings']} anuncios ativos.")
            print(f"[USUARIOS] {result['users']} contas preservadas.")
            print(f"[FECHAMENTOS] {protected} status comprovados mantidos.")
            print(f"[AUDITORIAS] {verification_imported} verificacoes novas importadas.")
            print(f"[RETIREMENT] {retirement_tombstones['imported']} registros confirmados "
                  f"importados | {retirement_tombstones['removed']} removidos | "
                  f"{retirement_tombstones['protected']} com dados pessoais preservados.")
            if accounts:
                print(f"[CONTAS IMPORTADAS] {accounts}")
            print(f"[BACKUP] {backup_path}")
            return result
        finally:
            conn.execute("DETACH DATABASE incoming")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-db", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--into-db", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--import-accounts", action="store_true",
                        help="Importar contas e favoritos criados no banco da aula")
    args = parser.parse_args()
    try:
        sync_catalog(args.from_db, args.into_db, include_accounts=args.import_accounts)
    except (SyncError, sqlite3.DatabaseError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
