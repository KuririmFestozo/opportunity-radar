from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from tools import sync_server_state as sync_module


def _create_sqlite(path: Path, marker: str = "new") -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE jobs (marker TEXT)")
    conn.execute("INSERT INTO jobs(marker) VALUES (?)", (marker,))
    conn.commit()
    conn.close()


def _marker(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return str(conn.execute("SELECT marker FROM jobs").fetchone()[0])
    finally:
        conn.close()


def _snapshot(tmp_path: Path, *, channel: str = "test-branch"):
    db = tmp_path / "remote.db"
    _create_sqlite(db, "remote")

    compressed = tmp_path / "remote.db.gz"
    with db.open("rb") as source, gzip.open(compressed, "wb") as target:
        shutil.copyfileobj(source, target)

    output_zip = tmp_path / "remote-output.zip"
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "<html>remote</html>")
        archive.writestr("jobs.json", "[]")
        archive.writestr("stats.json", "{}")
        archive.writestr("dashboard_data.json", "{}")
        archive.writestr("jobs.csv", "source,title\n")

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    metadata = {
        "channel": channel,
        "commit_sha": "abc123",
        "run_id": "42",
        "db_sha256": sha(db),
        "gzip_sha256": sha(compressed),
        "output_zip_sha256": sha(output_zip),
    }
    return db, compressed, output_zip, metadata


def _fake_download(compressed: Path, output_zip: Path):
    def download(url, destination):
        source = output_zip if url.endswith("-output.zip") else compressed
        shutil.copy2(source, destination)
    return download


def test_state_sync_installs_database_and_dashboard(tmp_path, monkeypatch):
    destination = tmp_path / "data" / "opportunity_radar.db"
    destination.parent.mkdir(parents=True)
    _create_sqlite(destination, "local")
    output_dir = tmp_path / "output"

    _, compressed, output_zip, metadata = _snapshot(tmp_path)

    monkeypatch.setattr(sync_module, "_download_json", lambda url: dict(metadata))
    monkeypatch.setattr(
        sync_module,
        "_download_file",
        _fake_download(compressed, output_zip),
    )

    result = sync_module.sync_server_state(
        db_path=destination,
        output_dir=output_dir,
        base_url="https://example.invalid/state",
        channel="test-branch",
        backup_dir=tmp_path / "backups",
    )

    assert result["updated"] is True
    assert _marker(destination) == "remote"
    assert (output_dir / "index.html").read_text() == "<html>remote</html>"
    assert list((tmp_path / "backups").glob("*.db"))


def test_checksum_failure_never_replaces_existing_database(
    tmp_path, monkeypatch
):
    destination = tmp_path / "opportunity_radar.db"
    _create_sqlite(destination, "local")
    _, compressed, output_zip, metadata = _snapshot(tmp_path)
    metadata["output_zip_sha256"] = "0" * 64

    monkeypatch.setattr(sync_module, "_download_json", lambda url: dict(metadata))
    monkeypatch.setattr(
        sync_module,
        "_download_file",
        _fake_download(compressed, output_zip),
    )

    with pytest.raises(sync_module.StateSyncError):
        sync_module.sync_server_state(
            db_path=destination,
            output_dir=tmp_path / "output",
            base_url="https://example.invalid/state",
            channel="test-branch",
            backup_dir=tmp_path / "backups",
        )

    assert _marker(destination) == "local"


def test_invalid_sqlite_never_replaces_existing_database(
    tmp_path, monkeypatch
):
    destination = tmp_path / "opportunity_radar.db"
    _create_sqlite(destination, "local")

    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"not-a-sqlite-database")
    compressed = tmp_path / "invalid.db.gz"
    with invalid.open("rb") as source, gzip.open(compressed, "wb") as target:
        shutil.copyfileobj(source, target)

    output_zip = tmp_path / "output.zip"
    with zipfile.ZipFile(output_zip, "w") as archive:
        for name, value in {
            "index.html": "<html></html>",
            "jobs.json": "[]",
            "stats.json": "{}",
            "dashboard_data.json": "{}",
        }.items():
            archive.writestr(name, value)

    metadata = {
        "channel": "test-branch",
        "commit_sha": "bad",
        "run_id": "99",
        "db_sha256": hashlib.sha256(invalid.read_bytes()).hexdigest(),
        "gzip_sha256": hashlib.sha256(compressed.read_bytes()).hexdigest(),
        "output_zip_sha256": hashlib.sha256(output_zip.read_bytes()).hexdigest(),
    }

    monkeypatch.setattr(sync_module, "_download_json", lambda url: dict(metadata))
    monkeypatch.setattr(
        sync_module,
        "_download_file",
        _fake_download(compressed, output_zip),
    )

    with pytest.raises(sync_module.StateSyncError):
        sync_module.sync_server_state(
            db_path=destination,
            output_dir=tmp_path / "output",
            base_url="https://example.invalid/state",
            channel="test-branch",
            backup_dir=tmp_path / "backups",
        )

    assert _marker(destination) == "local"


def test_up_to_date_snapshot_skips_downloads(tmp_path, monkeypatch):
    destination = tmp_path / "opportunity_radar.db"
    remote_db, _, _, metadata = _snapshot(tmp_path)
    shutil.copy2(remote_db, destination)
    destination.with_suffix(".state.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    for name in sync_module.REQUIRED_OUTPUT_FILES:
        (output_dir / name).write_text("ready", encoding="utf-8")

    monkeypatch.setattr(sync_module, "_download_json", lambda url: dict(metadata))

    called = {"download": False}

    def unexpected_download(url, dest):
        called["download"] = True

    monkeypatch.setattr(sync_module, "_download_file", unexpected_download)

    result = sync_module.sync_server_state(
        db_path=destination,
        output_dir=output_dir,
        base_url="https://example.invalid/state",
        channel="test-branch",
        backup_dir=tmp_path / "backups",
    )

    assert result["updated"] is False
    assert called["download"] is False


def test_output_bundle_rejects_path_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../evil.txt", "nope")
        for name in sync_module.REQUIRED_OUTPUT_FILES:
            bundle.writestr(name, "ok")

    with pytest.raises(sync_module.StateSyncError):
        sync_module._validate_output_zip(archive)


def test_start_server_uses_remote_runtime_without_local_rebuild():
    text = Path("start_server.ps1").read_text(encoding="utf-8")

    pull = text.index("git pull --ff-only")
    sync = text.index("tools.sync_server_state")
    server = text.index("python server.py")

    assert pull < sync < server
    assert "tools.rebuild_server_output" not in text
    assert "[switch]$Offline" in text


def test_daily_workflow_publishes_branch_scoped_runtime_bundle():
    workflow = Path(".github/workflows/daily-radar.yml").read_text(
        encoding="utf-8"
    )

    assert "contents: write" in workflow
    assert "radar-state-latest" in workflow
    assert "output_zip_sha256" in workflow

    publish = workflow.split(
        "      - name: Publish rolling server state\n", 1
    )[1].split(
        "      - name: Upload generated dashboard\n", 1
    )[0]

    db_asset = '"opportunity_radar-${STATE_CHANNEL}.db.gz"'
    output_asset = '"opportunity_radar-${STATE_CHANNEL}-output.zip"'
    metadata_asset = '"opportunity_radar-${STATE_CHANNEL}.state.json"'

    assert 'gh release upload "$TAG" \\\n' in publish
    assert db_asset in publish
    assert output_asset in publish
    assert metadata_asset in publish
    assert publish.index(db_asset) < publish.index(output_asset)
    assert publish.index(output_asset) < publish.index(metadata_asset)
    upload = publish.split('gh release upload "$TAG"', 1)[1]
    assert upload.index(db_asset) < upload.index(output_asset)
    assert upload.index(output_asset) < upload.index(metadata_asset)
    assert upload.index(metadata_asset) < upload.index(
        '--repo "$GITHUB_REPOSITORY"'
    )
    assert "--clobber" in upload
