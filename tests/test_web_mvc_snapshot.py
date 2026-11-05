"""The MVC snapshot helper must never corrupt or replace collector databases."""
import importlib.util
from pathlib import Path
import sqlite3

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "web-mvc" / "tools" / "prepare_sqlite_snapshot.py"
spec = importlib.util.spec_from_file_location("prepare_sqlite_snapshot", SCRIPT)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def make_source(path):
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE opportunities (id TEXT PRIMARY KEY);
            CREATE TABLE source_postings (source TEXT, source_job_id TEXT);
            CREATE TABLE opportunity_course_scores (opportunity_id TEXT, course_id TEXT);
            INSERT INTO opportunities VALUES ('one');
            INSERT INTO source_postings VALUES ('workday', 'one');
        """)


def test_consistent_snapshot_when_wal_connection_is_open(tmp_path):
    source, target = tmp_path / "original.db", tmp_path / "snapshot.db"
    make_source(source)
    with sqlite3.connect(source) as live_collector:
        live_collector.execute("PRAGMA journal_mode = WAL")
        live_collector.execute("INSERT INTO opportunities VALUES ('two')")
        live_collector.commit()
        result = snapshot.prepare_snapshot(source, target)
        assert result == {"opportunities": 2, "source_postings": 1}
        with sqlite3.connect(target) as copy:
            assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert copy.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 2
    with sqlite3.connect(source) as original:
        assert original.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 2


def test_refuses_existing_destination_without_overwriting(tmp_path):
    source, target = tmp_path / "original.db", tmp_path / "existing.db"
    make_source(source)
    target.write_bytes(b"do-not-overwrite")
    with pytest.raises(FileExistsError):
        snapshot.prepare_snapshot(source, target)
    assert target.read_bytes() == b"do-not-overwrite"
    with pytest.raises(FileExistsError):
        snapshot.prepare_snapshot(source, source)


def test_rejects_incomplete_checkpoint4_schema(tmp_path):
    source, target = tmp_path / "incomplete.db", tmp_path / "out.db"
    with sqlite3.connect(source) as c:
        c.execute("CREATE TABLE jobs (id TEXT)")
    with pytest.raises(ValueError, match="CP4"):
        snapshot.prepare_snapshot(source, target)
    assert not target.exists()
