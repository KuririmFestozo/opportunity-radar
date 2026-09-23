"""Download and safely install the latest Opportunity Radar server state."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import requests


DEFAULT_DB_PATH = Path("data/opportunity_radar.db")
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_RELEASE_BASE_URL = (
    "https://github.com/KuririmFestozo/opportunity-radar/"
    "releases/download/radar-state-latest"
)
DEFAULT_BACKUP_DIR = Path("data/backups")
DEFAULT_KEEP_BACKUPS = 3
REQUIRED_OUTPUT_FILES = {
    "index.html",
    "jobs.json",
    "stats.json",
    "dashboard_data.json",
}


class StateSyncError(RuntimeError):
    """Raised when the remote server state cannot be installed safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _channel_slug(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = value.strip("-._")
    return value or "main"


def _current_channel() -> str:
    override = os.getenv("OPPORTUNITY_RADAR_STATE_CHANNEL", "").strip()
    if override:
        return _channel_slug(override)

    try:
        completed = subprocess.run(
            ["git", "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
        )
        branch = completed.stdout.strip()
        if branch:
            return _channel_slug(branch)
    except OSError:
        pass

    return "main"


def _download_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise StateSyncError("Metadata remoto inválido.")
    return payload


def _download_file(url: str, destination: Path, *, timeout: int = 180) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def _validate_sqlite(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise StateSyncError("Snapshot SQLite vazio ou ausente.")

    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if not result or str(result[0]).lower() != "ok":
                raise StateSyncError(
                    f"PRAGMA integrity_check falhou: {result!r}"
                )
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise StateSyncError(f"SQLite inválido: {exc}") from exc

    if "jobs" not in tables and "opportunities" not in tables:
        raise StateSyncError(
            "Snapshot não contém tabelas reconhecidas do Opportunity Radar."
        )


def _validate_output_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set()
            for info in archive.infolist():
                if info.is_dir():
                    continue
                pure = PurePosixPath(info.filename)
                if pure.is_absolute() or ".." in pure.parts:
                    raise StateSyncError(
                        f"Caminho inseguro no bundle de output: {info.filename!r}"
                    )
                names.add(pure.as_posix())

            missing = REQUIRED_OUTPUT_FILES - names
            if missing:
                raise StateSyncError(
                    "Bundle de output incompleto: "
                    + ", ".join(sorted(missing))
                )

            bad = archive.testzip()
            if bad is not None:
                raise StateSyncError(
                    f"CRC inválido no bundle de output: {bad}"
                )
    except zipfile.BadZipFile as exc:
        raise StateSyncError(f"Bundle de output inválido: {exc}") from exc


def _install_output_zip(
    archive_path: Path,
    output_dir: Path,
    temp_dir: Path,
) -> None:
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(temp_dir)

        for source in sorted(temp_dir.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(temp_dir)
            destination = output_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _read_local_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def _backup_existing(
    db_path: Path,
    backup_dir: Path,
    *,
    keep_backups: int,
) -> Path | None:
    if not db_path.exists():
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"opportunity_radar-{stamp}.db"
    shutil.copy2(db_path, backup)

    backups = sorted(
        backup_dir.glob("opportunity_radar-*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old in backups[max(1, keep_backups):]:
        old.unlink(missing_ok=True)

    return backup


def _output_ready(output_dir: Path) -> bool:
    return all((output_dir / name).exists() for name in REQUIRED_OUTPUT_FILES)


def sync_server_state(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    base_url: str = DEFAULT_RELEASE_BASE_URL,
    channel: str | None = None,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    keep_backups: int = DEFAULT_KEEP_BACKUPS,
    force: bool = False,
) -> dict[str, Any]:
    channel = _channel_slug(channel or _current_channel())
    db_path = Path(db_path)
    output_dir = Path(output_dir)
    backup_dir = Path(backup_dir)
    state_path = db_path.with_suffix(".state.json")

    db_asset = f"opportunity_radar-{channel}.db.gz"
    output_asset = f"opportunity_radar-{channel}-output.zip"
    metadata_asset = f"opportunity_radar-{channel}.state.json"
    base_url = base_url.rstrip("/")

    print(f"[SYNC] Canal de estado: {channel}", flush=True)
    print("[SYNC] Consultando metadata do snapshot...", flush=True)
    metadata = _download_json(f"{base_url}/{metadata_asset}")

    expected_channel = _channel_slug(str(metadata.get("channel") or ""))
    if expected_channel != channel:
        raise StateSyncError(
            f"Canal do metadata ({expected_channel}) difere do solicitado ({channel})."
        )

    expected_db_sha = str(metadata.get("db_sha256") or "").strip().lower()
    expected_gzip_sha = str(metadata.get("gzip_sha256") or "").strip().lower()
    expected_output_sha = str(
        metadata.get("output_zip_sha256") or ""
    ).strip().lower()

    if not all(
        len(value) == 64
        for value in (expected_db_sha, expected_gzip_sha, expected_output_sha)
    ):
        raise StateSyncError(
            "Metadata remoto não contém checksums SHA-256 válidos."
        )

    if db_path.exists() and not force:
        local_state = _read_local_state(state_path)
        if (
            str(local_state.get("db_sha256") or "").lower() == expected_db_sha
            and str(local_state.get("output_zip_sha256") or "").lower()
            == expected_output_sha
            and _sha256(db_path) == expected_db_sha
            and _output_ready(output_dir)
        ):
            _validate_sqlite(db_path)
            print(
                "[SYNC] Banco e dashboard locais já correspondem ao snapshot "
                f"remoto (run {metadata.get('run_id', '?')}).",
                flush=True,
            )
            return {
                "updated": False,
                "channel": channel,
                "db_path": str(db_path),
                "output_dir": str(output_dir),
                "metadata": metadata,
                "backup": None,
            }

    db_path.parent.mkdir(parents=True, exist_ok=True)
    sync_dir = db_path.parent / "server-sync"
    sync_dir.mkdir(parents=True, exist_ok=True)

    compressed = sync_dir / db_asset
    incoming = sync_dir / "opportunity_radar.db.incoming"
    output_zip = sync_dir / output_asset
    output_temp = sync_dir / "output-incoming"

    for path in (compressed, incoming, output_zip):
        path.unlink(missing_ok=True)
    shutil.rmtree(output_temp, ignore_errors=True)

    try:
        print("[SYNC] Baixando snapshot SQLite...", flush=True)
        _download_file(f"{base_url}/{db_asset}", compressed)

        print("[SYNC] Baixando dashboard gerado...", flush=True)
        _download_file(f"{base_url}/{output_asset}", output_zip)

        if _sha256(compressed) != expected_gzip_sha:
            raise StateSyncError(
                "Checksum do arquivo SQLite comprimido não confere."
            )
        if _sha256(output_zip) != expected_output_sha:
            raise StateSyncError(
                "Checksum do bundle de dashboard não confere."
            )

        print("[SYNC] Descomprimindo SQLite...", flush=True)
        try:
            with gzip.open(compressed, "rb") as source, incoming.open("wb") as target:
                shutil.copyfileobj(source, target)
        except (OSError, EOFError) as exc:
            raise StateSyncError(f"Snapshot gzip inválido: {exc}") from exc

        if _sha256(incoming) != expected_db_sha:
            raise StateSyncError(
                "Checksum do SQLite descomprimido não confere."
            )

        print("[SYNC] Validando SQLite...", flush=True)
        _validate_sqlite(incoming)

        print("[SYNC] Validando dashboard...", flush=True)
        _validate_output_zip(output_zip)

        backup = _backup_existing(
            db_path,
            backup_dir,
            keep_backups=max(1, keep_backups),
        )

        print("[SYNC] Instalando dashboard...", flush=True)
        _install_output_zip(output_zip, output_dir, output_temp)

        print("[SYNC] Instalando banco...", flush=True)
        os.replace(incoming, db_path)
        _write_json_atomic(state_path, metadata)

        print(
            "[OK] Estado atualizado: "
            f"commit {metadata.get('commit_sha', '?')} "
            f"| run {metadata.get('run_id', '?')}",
            flush=True,
        )
        if backup is not None:
            print(f"[BACKUP] {backup}", flush=True)

        return {
            "updated": True,
            "channel": channel,
            "db_path": str(db_path),
            "output_dir": str(output_dir),
            "metadata": metadata,
            "backup": str(backup) if backup else None,
        }
    finally:
        compressed.unlink(missing_ok=True)
        incoming.unlink(missing_ok=True)
        output_zip.unlink(missing_ok=True)
        shutil.rmtree(output_temp, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa e instala o SQLite e o dashboard mais recentes "
            "publicados pelo workflow do Opportunity Radar."
        )
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base-url", default=DEFAULT_RELEASE_BASE_URL)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--keep-backups", type=int, default=DEFAULT_KEEP_BACKUPS)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        sync_server_state(
            db_path=args.db_path,
            output_dir=args.output_dir,
            base_url=args.base_url,
            channel=args.channel,
            backup_dir=args.backup_dir,
            keep_backups=args.keep_backups,
            force=args.force,
        )
    except (StateSyncError, requests.RequestException, OSError) as exc:
        print(f"[ERRO] Falha ao sincronizar estado do servidor: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
