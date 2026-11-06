"""Pull the latest main-branch SQLite snapshot into a *separate* classroom DB.

The private repository requires GitHub CLI authentication:
    gh auth login
    python tools/pull_classroom_db.py

This never replaces web-mvc/radar-web.db, which holds users and favorites,
or data/opportunity_radar.db, which belongs to the local collector.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = ROOT / "data" / "classroom_latest.db"
REPO = "KuririmFestozo/opportunity-radar"
RELEASE = "radar-state-latest"
GZIP_NAME = "opportunity_radar-main.db.gz"
METADATA_NAME = "opportunity_radar-main.state.json"
REQUIRED_TABLES = frozenset({"opportunities", "source_postings", "opportunity_course_scores"})
PRIVATE_TABLES = ("web_users", "web_device_favorites", "web_device_applications",
                  "web_favorites", "web_applications")


class ClassroomPullError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_release(folder: Path) -> None:
    cli = shutil.which("gh")
    if cli is None:
        raise ClassroomPullError(
            "GitHub CLI (gh) nao encontrado. Instale com: "
            "winget install --id GitHub.cli -e; depois execute: gh auth login"
        )
    command = [
        cli, "release", "download", RELEASE, "--repo", REPO,
        "--pattern", GZIP_NAME, "--pattern", METADATA_NAME,
        "--dir", str(folder),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ClassroomPullError(
            "Nao foi possivel baixar o snapshot privado com o GitHub CLI. "
            "Confira: gh auth status; se necessario, execute gh auth login. "
            + detail[:500]
        )


def _metadata(path: Path) -> dict[str, Any]:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClassroomPullError("Metadata do release invalido ou ausente.") from exc
    if not isinstance(metadata, dict) or metadata.get("channel") != "main":
        raise ClassroomPullError("Snapshot nao pertence a branch main.")
    for key in ("db_sha256", "gzip_sha256"):
        check = metadata.get(key)
        if not isinstance(check, str) or len(check) != 64 or any(
            char not in "0123456789abcdef" for char in check.lower()
        ):
            raise ClassroomPullError(f"Checksum SHA-256 invalido: {key}.")
    return metadata


def _validate_db(path: Path) -> dict[str, int]:
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            check = connection.execute("PRAGMA integrity_check").fetchone()
            if check != ("ok",):
                raise ClassroomPullError(f"SQLite com erro de integridade: {check}")
            tables = {
                name for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not REQUIRED_TABLES.issubset(tables):
                missing = ", ".join(sorted(REQUIRED_TABLES - tables))
                raise ClassroomPullError(
                    f"Snapshot incompleto para o site Java. Tabelas ausentes: {missing}."
                )
            counts = {
                table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in sorted(REQUIRED_TABLES)
            }
            if counts["opportunities"] <= 0:
                raise ClassroomPullError("Snapshot sem oportunidades; nao sera instalado.")
            return counts
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise ClassroomPullError(f"SQLite invalido: {exc}") from exc


def _has_private_data(path: Path) -> bool:
    """Refuse to replace a classroom file if the user began saving accounts."""
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {
                name for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            return any(
                connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                for table in PRIVATE_TABLES if table in tables
            )
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise ClassroomPullError(
            "O destino existente nao e um SQLite valido; nao sera sobrescrito."
        ) from exc


def pull_classroom_db(destination: Path = DEFAULT_DESTINATION) -> dict[str, Any]:
    destination = destination.expanduser().resolve()
    if destination.suffix.lower() != ".db":
        raise ClassroomPullError("O destino deve ser um arquivo .db.")
    protected = {
        (ROOT / "web-mvc" / "radar-web.db").resolve(),
        (ROOT / "data" / "opportunity_radar.db").resolve(),
    }
    if destination in protected:
        raise ClassroomPullError(
            "Nao substitua o banco do site (usuarios/favoritos) nem o do coletor. "
            "Use data/classroom_latest.db."
        )
    if not destination.parent.is_dir():
        raise ClassroomPullError(f"Pasta de destino nao encontrada: {destination.parent}")
    if destination.exists() and _has_private_data(destination):
        raise ClassroomPullError(
            "Este SQLite ja contem usuarios, favoritos ou candidaturas. "
            "Nao vou sobrescrever esses dados. Use outro nome em --output."
        )
    if any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm")):
        raise ClassroomPullError(
            "Ha arquivos WAL/SHM neste destino, possivelmente aberto pelo site. "
            "Pare o Spring Boot antes de atualizar o snapshot."
        )

    print("[PULL] Baixando o snapshot mais recente da main via GitHub Release...", flush=True)
    with tempfile.TemporaryDirectory(prefix="radar-aula-", dir=destination.parent) as folder:
        temp = Path(folder)
        _download_release(temp)
        compressed = temp / GZIP_NAME
        metadata = _metadata(temp / METADATA_NAME)
        if not compressed.is_file():
            raise ClassroomPullError("Arquivo SQLite .gz nao foi baixado.")
        if _hash(compressed) != metadata["gzip_sha256"]:
            raise ClassroomPullError("Checksum do arquivo comprimido nao confere.")
        incoming = temp / "incoming.db"
        try:
            with gzip.open(compressed, "rb") as source, incoming.open("wb") as target:
                shutil.copyfileobj(source, target)
        except (OSError, EOFError) as exc:
            raise ClassroomPullError("Erro ao descomprimir o snapshot SQLite.") from exc
        if _hash(incoming) != metadata["db_sha256"]:
            raise ClassroomPullError("Checksum do banco descomprimido nao confere.")
        if metadata.get("db_bytes") is not None and incoming.stat().st_size != metadata["db_bytes"]:
            raise ClassroomPullError("Tamanho do SQLite nao corresponde ao metadata.")

        counts = _validate_db(incoming)
        backup = None
        if destination.exists():
            backup_dir = destination.parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = backup_dir / f"{destination.stem}-{stamp}.db"
            # Snapshot of existing local classroom data even if the file uses WAL.
            with sqlite3.connect(destination) as original, sqlite3.connect(backup) as saved:
                original.backup(saved)
        # Atomic on the same filesystem. If destination is open on Windows,
        # the replace fails and the original remains untouched.
        os.replace(incoming, destination)
        state_path = destination.with_suffix(".state.json")
        state_temp = temp / "state.json"
        state_temp.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        os.replace(state_temp, state_path)

    print(
        f"[OK] Banco da aula: {destination}\n"
        f"[OK] {counts['opportunities']:,} oportunidades, "
        f"{counts['source_postings']:,} anuncios; "
        f"run {metadata.get('run_id', '?')}."
    )
    if backup:
        print(f"[BACKUP] Copia anterior em: {backup}")
    print("[SEGURO] web-mvc/radar-web.db nao foi alterado.")
    return {"destination": str(destination), "counts": counts,
            "run_id": metadata.get("run_id"), "backup": str(backup) if backup else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_DESTINATION,
                        help="SQLite separado para a aula (padrao data/classroom_latest.db)")
    args = parser.parse_args()
    try:
        pull_classroom_db(args.output)
    except (ClassroomPullError, OSError, sqlite3.DatabaseError) as exc:
        print(f"[ERRO] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
