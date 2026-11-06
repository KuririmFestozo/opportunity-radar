"""Full sweep: exact coverage, safe statuses, private data and restore checks."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from tools import full_availability_sweep as sweep


def db_fixture(path: Path):
    with sqlite3.connect(path) as c:
        c.executescript("""
          CREATE TABLE opportunities(id TEXT PRIMARY KEY);
          CREATE TABLE source_postings(
            source TEXT,source_job_id TEXT,url TEXT,opportunity_id TEXT,
            is_active INTEGER NOT NULL,inactive_at TEXT,last_checked_at TEXT,
            PRIMARY KEY(source,source_job_id)
          );
          CREATE TABLE jobs(source TEXT,source_job_id TEXT,is_active INTEGER NOT NULL,
            inactive_at TEXT,last_checked_at TEXT,
            PRIMARY KEY(source,source_job_id));
          CREATE TABLE web_users(id TEXT PRIMARY KEY,username TEXT);
          CREATE TABLE web_device_favorites(id TEXT PRIMARY KEY,
            owner_id TEXT,opportunity_id TEXT);
          CREATE TABLE web_device_applications(id TEXT PRIMARY KEY,
            owner_id TEXT,opportunity_id TEXT,notes TEXT);
          INSERT INTO web_users VALUES ('u1','tester');
          INSERT INTO web_device_favorites VALUES ('f1','u1','opp-0');
          INSERT INTO web_device_applications VALUES ('a1','u1','opp-0','Preserve');
        """)
        records = [
            ("99jobs", "a", "https://99jobs.com/kabum/jobs/512644", 1),
            ("gupy_global", "b", "https://a.gupy.io/jobs/123", 1),
            ("workday", "c", "https://demo.myworkdayjobs.com/job/123", 1),
            ("unknown_future", "d", "https://example.com/x", 1),
            ("gupy_global", "history", "https://a.gupy.io/jobs/456", 0),
        ]
        for i, (source, job_id, url, active) in enumerate(records):
            c.execute("INSERT INTO opportunities VALUES (?)", (f"opp-{i}",))
            c.execute("INSERT INTO source_postings VALUES (?,?,?,?,?,?,?)",
                      (source, job_id, url, f"opp-{i}", active, None, None))
            c.execute("INSERT INTO jobs VALUES (?,?,?,?,?)",
                      (source, job_id, active, None, None))


def fake_probe(source, url):
    if source == "99jobs":
        return "closed", "explicit_closed_message"
    if source == "gupy_global":
        return "open", "explicit_applications_open"
    return "unverified", "http_429"


def test_complete_parallel_sweep_preserves_accounts_and_history(tmp_path, monkeypatch):
    db = tmp_path / "sample.db"
    db_fixture(db)
    monkeypatch.setattr(sweep, "probe", fake_probe)
    artifacts = tmp_path / "artifacts"
    for shard in range(3):
        sweep.scan_shard(db, shard=shard, shards=3,
                         out=artifacts / f"availability-shard-{shard}", workers=2)
    report = sweep.merge_shards(
        db, results=artifacts, shards=3, summary_path=tmp_path / "report.json"
    )
    assert report["examined_active_postings"] == 4
    assert report["verified_closed"] == report["deactivated"] == 1
    assert report["unverified"] == 2
    assert report["verified_open"] == 1
    assert report["source_families"] == 4
    assert report["historical_postings"] == 5
    assert len(report["coverage"]) == 4
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM source_postings").fetchone()[0] == 5
        assert c.execute(
            "SELECT is_active FROM source_postings WHERE source='99jobs'"
        ).fetchone()[0] == 0
        assert c.execute(
            "SELECT is_active FROM source_postings WHERE source='workday'"
        ).fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM web_users").fetchone()[0] == 1
        assert c.execute("SELECT notes FROM web_device_applications").fetchone() == ("Preserve",)
        assert c.execute(
            "SELECT verdict FROM source_availability_checks "
            "WHERE source='unknown_future'"
        ).fetchone() == ("unverified",)


def test_missing_shard_prevents_any_write(tmp_path, monkeypatch):
    db = tmp_path / "sample.db"
    db_fixture(db)
    monkeypatch.setattr(sweep, "probe", fake_probe)
    folder = tmp_path / "result"
    sweep.scan_shard(db, shard=0, shards=2,
                     out=folder / "availability-shard-0", workers=1)
    with pytest.raises(FileNotFoundError):
        sweep.merge_shards(db, results=folder, shards=2,
                           summary_path=tmp_path / "summary.json")
    with sqlite3.connect(db) as c:
        assert c.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE name='source_availability_checks'"
        ).fetchone()[0] == 0


def test_changed_database_is_rejected_before_merge(tmp_path, monkeypatch):
    db = tmp_path / "sample.db"
    db_fixture(db)
    monkeypatch.setattr(sweep, "probe", fake_probe)
    folder = tmp_path / "result"
    sweep.scan_shard(db, shard=0, shards=1,
                     out=folder / "availability-shard-0", workers=1)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO opportunities VALUES ('NEW')")
    with pytest.raises(sweep.SweepError, match="outro snapshot"):
        sweep.merge_shards(db, results=folder, shards=1,
                           summary_path=tmp_path / "summary.json")


def test_modified_or_duplicate_patch_is_rejected(tmp_path, monkeypatch):
    db = tmp_path / "sample.db"
    db_fixture(db)
    monkeypatch.setattr(sweep, "probe", fake_probe)
    folder = tmp_path / "result"
    subfolder = folder / "availability-shard-0"
    sweep.scan_shard(db, shard=0, shards=1, out=subfolder, workers=1)
    p = subfolder / "verdicts.jsonl"
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines + [lines[0]]) + "\n")
    with pytest.raises(sweep.SweepError, match="repetida"):
        sweep.merge_shards(db, results=folder, shards=1,
                           summary_path=tmp_path / "summary.json")


def test_signed_snapshot_round_trip_and_invalid_hash(tmp_path):
    db = tmp_path / "source.db"
    db_fixture(db)
    archive = tmp_path / "source.db.gz"
    with gzip.open(archive, "wb") as dest, db.open("rb") as source:
        shutil.copyfileobj(source, dest)
    meta = tmp_path / "source.state.json"
    info = {
        "channel": "main", "db_sha256": sweep.sha256(db),
        "gzip_sha256": sweep.sha256(archive), "db_bytes": db.stat().st_size,
        "output_zip_sha256": "9" * 64,
    }
    meta.write_text(json.dumps(info))
    target = tmp_path / "target.db"
    sweep.restore(archive, meta, target)
    assert sweep.sha256(target) == sweep.sha256(db)
    info["gzip_sha256"] = "0" * 64
    meta.write_text(json.dumps(info))
    with pytest.raises(sweep.SweepError, match="Checksum"):
        sweep.restore(archive, meta, target)
    assert sweep.sha256(target) == sweep.sha256(db)


def test_pack_keeps_existing_dashboard_digest(tmp_path):
    db = tmp_path / "source.db"
    db_fixture(db)
    summary = tmp_path / "report.json"
    summary.write_text(json.dumps({
        "examined_active_postings": 4, "verified_closed": 1,
        "unverified": 2, "deactivated": 1
    }))
    old = tmp_path / "old.json"
    old.write_text(json.dumps({
        "channel": "main", "db_sha256": "0" * 64,
        "gzip_sha256": "0" * 64, "output_zip_sha256": "9" * 64,
    }))
    out = tmp_path / "publish"
    sweep.pack(db, old, summary, out)
    updated = json.loads((out / "opportunity_radar-main.state.json").read_text())
    assert updated["db_sha256"] == sweep.sha256(db)
    assert updated["output_zip_sha256"] == "9" * 64
    assert updated["availability_full_audit"]["examined"] == 4


def test_shard_hash_is_stable_and_handles_unicode():
    assert sweep.shard_number("gupy_global", "123", 12) == sweep.shard_number(
        "gupy_global", "123", 12
    )
    assert 0 <= sweep.shard_number("ciee", "estágio-ç", 12) < 12



def test_render_fallback_only_overrides_inconclusive_eligible_jobs(tmp_path, monkeypatch):
    db = tmp_path / "sample.db"
    db_fixture(db)
    monkeypatch.setattr(sweep, "probe", lambda source, url:
                        ("unverified", "no_confirmed_application_state"))
    selected = []
    def fake_render(candidates, **kwargs):
        selected.extend(candidates)
        # Return a forged extra key: even if a buggy renderer returns
        # more rows, no other posting can be inadvertently closed.
        return {
            ("workday", "c"): ("closed", "rendered_explicit_closed_message"),
            ("unknown_future", "d"): ("closed", "rendered_explicit_closed_message"),
        }
    monkeypatch.setattr(sweep, "render_batch", fake_render)
    manifest = sweep.scan_shard(
        db, shard=0, shards=1, out=tmp_path / "results",
        workers=1, render_limit=10
    )
    assert manifest["rendered_attempted"] == 3
    assert manifest["rendered_confirmed"] == 1
    assert manifest["counts"]["closed"] == 1
    assert manifest["counts"]["unverified"] == 3
    assert all(source != "unknown_future" for source, _, _ in selected)
    with sqlite3.connect(db) as c:
        assert c.execute(
            "SELECT count(*) FROM source_postings WHERE is_active=1"
        ).fetchone()[0] == 4  # The shard itself never modifies SQLite.
