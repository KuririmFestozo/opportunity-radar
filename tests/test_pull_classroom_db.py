"""Regression tests: download classroom data without deleting account state."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "pull_classroom_db.py"
spec = importlib.util.spec_from_file_location("pull_classroom_db", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_fixture(db: Path, with_user: bool = False) -> None:
    # sqlite3.Connection.__exit__ commits but DOES NOT CLOSE the handle.
    # On Windows that would keep classroom.db locked through os.replace().
    with closing(sqlite3.connect(db)) as connection:
        connection.executescript("""
            CREATE TABLE opportunities (id TEXT PRIMARY KEY);
            CREATE TABLE source_postings (source TEXT, source_job_id TEXT);
            CREATE TABLE opportunity_course_scores (opportunity_id TEXT, course_id TEXT);
            INSERT INTO opportunities VALUES ('a');
            INSERT INTO source_postings VALUES ('demo','1');
        """)
        if with_user:
            connection.execute("CREATE TABLE web_users (id TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO web_users VALUES ('account1')")
        connection.commit()


def fake_release(monkeypatch, db: Path, corrupt_gzip: bool = False):
    raw = db.read_bytes()
    gz = gzip.compress(raw)
    metadata = {
        "channel": "main",
        "run_id": "12345",
        "db_sha256": hashlib.sha256(raw).hexdigest(),
        "gzip_sha256": hashlib.sha256(gz).hexdigest(),
        "db_bytes": len(raw),
    }
    if corrupt_gzip:
        gz = gz[:-6] + b"broken"

    def download(folder):
        (folder / module.GZIP_NAME).write_bytes(gz)
        (folder / module.METADATA_NAME).write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(module, "_download_release", download)


def test_downloads_validated_classroom_snapshot_without_touching_web_db(tmp_path, monkeypatch):
    remote, local, web = (tmp_path / item for item in ("remote.db", "classroom.db", "radar-web.db"))
    write_fixture(remote)
    write_fixture(web, with_user=True)
    fake_release(monkeypatch, remote)
    result = module.pull_classroom_db(local)
    assert result["run_id"] == "12345"
    assert result["counts"]["opportunities"] == 1
    with sqlite3.connect(local) as conn:
        assert conn.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 1
    with sqlite3.connect(web) as conn:
        assert conn.execute("SELECT count(*) FROM web_users").fetchone()[0] == 1
    assert local.with_suffix(".state.json").exists()


def test_refresh_creates_backup_of_existing_classroom_snapshot(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote.db", tmp_path / "classroom.db"
    write_fixture(remote)
    write_fixture(local)
    fake_release(monkeypatch, remote)
    result = module.pull_classroom_db(local)
    assert result["backup"] is not None
    assert Path(result["backup"]).exists()
    with sqlite3.connect(Path(result["backup"])) as original:
        assert original.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 1


def test_never_overwrites_user_accounts_or_favorites(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote.db", tmp_path / "classroom.db"
    write_fixture(remote)
    write_fixture(local, with_user=True)
    fake_release(monkeypatch, remote)
    with pytest.raises(module.ClassroomPullError, match="usuarios"):
        module.pull_classroom_db(local)
    with sqlite3.connect(local) as conn:
        assert conn.execute("SELECT count(*) FROM web_users").fetchone()[0] == 1


def test_invalid_checksum_keeps_existing_db_intact(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote.db", tmp_path / "classroom.db"
    write_fixture(remote)
    write_fixture(local)
    original = local.read_bytes()
    fake_release(monkeypatch, remote, corrupt_gzip=True)
    with pytest.raises(module.ClassroomPullError, match="Checksum"):
        module.pull_classroom_db(local)
    assert local.read_bytes() == original


def test_missing_catalog_table_prevents_install(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote.db", tmp_path / "classroom.db"
    with closing(sqlite3.connect(remote)) as conn, conn:
        conn.execute("CREATE TABLE opportunities (id TEXT)")
        conn.execute("INSERT INTO opportunities VALUES ('a')")
    fake_release(monkeypatch, remote)
    with pytest.raises(module.ClassroomPullError, match="Tabelas ausentes"):
        module.pull_classroom_db(local)
    assert not local.exists()


def test_disallows_targeting_live_collector_or_web_database():
    with pytest.raises(module.ClassroomPullError, match="Nao substitua"):
        module.pull_classroom_db(module.ROOT / "web-mvc" / "radar-web.db")
    with pytest.raises(module.ClassroomPullError, match="Nao substitua"):
        module.pull_classroom_db(module.ROOT / "data" / "opportunity_radar.db")


def test_fixture_releases_windows_sqlite_file_handle(tmp_path):
    """A finished fixture must not prevent Windows from replacing its file."""
    db = tmp_path / "classroom.db"
    replacement = tmp_path / "next.db"
    write_fixture(db)
    write_fixture(replacement)
    replacement.replace(db)
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone() == (1,)
