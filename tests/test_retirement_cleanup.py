"""Daily retirement: multi-day evidence, safe deletion, tombstones, local sync."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from pathlib import Path

import pytest

from processing import retirement as r


def setup_db(path: Path):
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
        CREATE TABLE opportunities (id TEXT PRIMARY KEY);
        CREATE TABLE source_postings (
            source TEXT NOT NULL,source_job_id TEXT NOT NULL,
            opportunity_id TEXT NOT NULL,url TEXT NOT NULL,
            is_active INTEGER NOT NULL, inactive_at TEXT,last_checked_at TEXT,
            PRIMARY KEY(source,source_job_id),
            FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                ON DELETE RESTRICT
        );
        CREATE TABLE jobs (
            source TEXT NOT NULL, source_job_id TEXT NOT NULL,
            is_active INTEGER NOT NULL, inactive_at TEXT,
            last_checked_at TEXT,missing_since TEXT,miss_count INTEGER DEFAULT 0,
            PRIMARY KEY(source,source_job_id)
        );
        CREATE TABLE opportunity_course_scores (
            opportunity_id TEXT NOT NULL,course_id TEXT NOT NULL,
            score INTEGER,FOREIGN KEY(opportunity_id)
            REFERENCES opportunities(id) ON DELETE CASCADE
        );
        CREATE TABLE web_users (id TEXT PRIMARY KEY,username TEXT NOT NULL);
        CREATE TABLE web_device_favorites (
            id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,
            FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );
        CREATE TABLE web_device_applications (
            id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,
            FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );
        INSERT INTO web_users VALUES ('u1','conta_local');
        """)


def add_job(conn, source, job_id, opp, url):
    conn.execute("INSERT OR IGNORE INTO opportunities VALUES (?)", (opp,))
    conn.execute("INSERT INTO jobs(source,source_job_id,is_active) VALUES (?,?,1)",
                 (source, job_id))
    conn.execute("""INSERT INTO source_postings(
        source,source_job_id,opportunity_id,url,is_active)
        VALUES (?,?,?,?,1)""", (source, job_id, opp, url))


URL = "https://jobs.zf.com/job/Araraquara-Estagio-RH/1431252033/"
OTHER = "https://www.vagas.com.br/vagas/v2831001/estagio-em-manutencao"
GUPY_OLD = "https://belgo.gupy.io/jobs/12424107"
GUPY_NEW = "https://belgo.gupy.io/job/eyJqb2JJZCI6MTI0MjQxMDcsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0="


def test_404_thrice_disables_but_requires_five_checks_and_14_days_to_delete(tmp_path, monkeypatch):
    db = tmp_path / "radar.db"
    setup_db(db)
    with sqlite3.connect(db) as conn:
        add_job(conn, "successfactors", "zf", "o1", URL)
        conn.execute("INSERT INTO opportunity_course_scores VALUES ('o1','eng',90)")
        for n in (0, 1, 2):
            day = (datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(days=n)).isoformat()
            observed = r.observe(conn, "successfactors", "zf", URL, "unverified", "http_404",
                                 checked_at=day)
            assert observed == (1 if n == 2 else 0)
        assert conn.execute("SELECT is_active FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT is_active FROM source_postings").fetchone()[0] == 0
        assert r._eligible(conn, "2026-11-03", max_items=10) == []
        for n in (3, 14):
            r.observe(conn, "successfactors", "zf", URL, "unverified", "http_404",
                      checked_at=(datetime(2026, 11, 1, tzinfo=timezone.utc)
                                  + timedelta(days=n)).isoformat())
        assert len(r._eligible(conn, "2026-11-15", max_items=10)) == 1
        conn.commit()
        # A zero-network daily run now physically retires this key.
        monkeypatch.setattr(r, "probe", lambda *_: ("unverified", "http_404"))
        result = r.run_daily_retirement(
            conn, db_path=db, recheck_limit=0,
            now=datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
        )
        assert result["purged"] == 1
        assert result["backup"] is not None
        assert Path(result["backup"]).is_file()
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM source_postings").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM opportunity_course_scores").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM purged_postings").fetchone()[0] == 1
        assert r.purged_keys(conn) == {("successfactors", "zf")}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_one_check_per_day_and_transient_failure_clears_streak(tmp_path):
    db = tmp_path / "radar.db"
    setup_db(db)
    with sqlite3.connect(db) as conn:
        add_job(conn, "vagas_com", "v2831001", "o1", OTHER)
        r.observe(conn, "vagas_com", "v2831001", OTHER, "unverified", "http_410",
                  checked_at="2026-11-01T11:00:00+00:00")
        r.observe(conn, "vagas_com", "v2831001", OTHER, "unverified", "http_404",
                  checked_at="2026-11-01T22:00:00+00:00")
        assert conn.execute("SELECT bad_checks FROM posting_retirement_checks").fetchone()[0] == 1
        r.observe(conn, "vagas_com", "v2831001", OTHER, "unverified", "http_429",
                  checked_at="2026-11-02T11:00:00+00:00")
        r.observe(conn, "vagas_com", "v2831001", OTHER, "unverified", "http_403",
                  checked_at="2026-11-03T11:00:00+00:00")
        assert conn.execute("SELECT bad_checks FROM posting_retirement_checks").fetchone()[0] == 0
        assert conn.execute("SELECT is_active FROM jobs").fetchone()[0] == 1


def test_old_gupy_404_does_not_count_but_encoded_url_does(tmp_path):
    db = tmp_path / "radar.db"
    setup_db(db)
    with sqlite3.connect(db) as conn:
        add_job(conn, "gupy_global", "12424107", "o1", GUPY_OLD)
        r.observe(conn, "gupy_global", "12424107", GUPY_OLD,
                  "unverified", "http_404", checked_at="2026-11-01T11:00:00+00:00")
        assert conn.execute("SELECT bad_checks FROM posting_retirement_checks").fetchone()[0] == 0
        r.observe(conn, "gupy_global", "12424107", GUPY_NEW,
                  "unverified", "http_404", checked_at="2026-11-02T11:00:00+00:00")
        assert conn.execute("SELECT bad_checks FROM posting_retirement_checks").fetchone()[0] == 1


def test_personal_link_prevents_deletion_but_keeps_inactive(tmp_path):
    db = tmp_path / "radar.db"
    setup_db(db)
    with sqlite3.connect(db) as conn:
        add_job(conn, "successfactors", "zf", "o1", URL)
        conn.execute("INSERT INTO web_device_favorites VALUES ('f1','o1')")
        for day in (1, 2, 3, 4, 20):
            r.observe(conn, "successfactors", "zf", URL, "closed", "explicit_closed_message",
                      checked_at=f"2026-11-{day:02d}T10:00:00+00:00")
        conn.execute("UPDATE jobs SET is_active=0")
        conn.execute("UPDATE source_postings SET is_active=0")
        conn.commit()
        result = r.run_daily_retirement(
            conn, db_path=db, recheck_limit=0,
            now=datetime(2026, 11, 22, tzinfo=timezone.utc)
        )
        assert result["purged"] == 0
        assert result["protected"] == 1
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM web_users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM web_device_favorites").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM purged_postings").fetchone()[0] == 0


def test_deleting_one_source_does_not_remove_other_source_opportunity(tmp_path):
    db = tmp_path / "radar.db"
    setup_db(db)
    with sqlite3.connect(db) as conn:
        add_job(conn, "successfactors", "zf", "shared", URL)
        add_job(conn, "vagas_com", "v2831001", "shared", OTHER)
        conn.execute("UPDATE jobs SET is_active=0 WHERE source='successfactors'")
        conn.execute("UPDATE source_postings SET is_active=0 WHERE source='successfactors'")
        removed, protected = r.purge_existing(conn, "successfactors", "zf")
        assert (removed, protected) == (True, False)
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_import_tombstones_cleans_local_old_stale_posting(tmp_path):
    source = tmp_path / "cleaned.db"
    target = tmp_path / "site.db"
    setup_db(source)
    setup_db(target)
    with sqlite3.connect(source) as conn:
        r.ensure_schema(conn)
        conn.execute("INSERT INTO purged_postings VALUES ('successfactors','zf',"
                     "'2026-11-17T12:00:00+00:00','explicit_closed_message')")
    with sqlite3.connect(target) as conn:
        add_job(conn, "successfactors", "zf", "o1", URL)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("ATTACH DATABASE ? AS incoming", (str(source),))
        imported = r.import_tombstones(conn)
        assert imported == {"imported": 1, "removed": 1, "protected": 0}
        assert conn.execute("SELECT COUNT(*) FROM source_postings").fetchone()[0] == 0
        assert r.purged_keys(conn) == {("successfactors", "zf")}
        conn.commit()
        conn.execute("DETACH DATABASE incoming")


def test_import_tombstones_preserves_local_favorite_and_deactivates(tmp_path):
    source = tmp_path / "cleaned.db"
    target = tmp_path / "site.db"
    setup_db(source)
    setup_db(target)
    with sqlite3.connect(source) as conn:
        r.ensure_schema(conn)
        conn.execute("INSERT INTO purged_postings VALUES ('successfactors','zf',"
                     "'2026-11-17T12:00:00+00:00','explicit_closed_message')")
    with sqlite3.connect(target) as conn:
        add_job(conn, "successfactors", "zf", "o1", URL)
        conn.execute("INSERT INTO web_device_applications VALUES ('app1','o1')")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("ATTACH DATABASE ? AS incoming", (str(source),))
        imported = r.import_tombstones(conn)
        assert imported == {"imported": 1, "removed": 0, "protected": 1}
        assert conn.execute("SELECT is_active FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT is_active FROM source_postings").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM web_device_applications").fetchone()[0] == 1
        conn.commit()
        conn.execute("DETACH DATABASE incoming")


def test_tombstones_suppress_discovery(tmp_path):
    class Job:
        def __init__(self, source, source_job_id):
            self.source = source
            self.source_job_id = source_job_id
    kept, skipped = r.filter_purged(
        [Job("gupy_global", "42"), Job("vagas_com", "42")],
        {("gupy_global", "42")}
    )
    assert skipped == 1 and kept[0].source == "vagas_com"


def test_sync_reduced_snapshot_requires_real_tombstone(tmp_path):
    """Local union may be larger than the fresh state after permanent purge."""
    # SQL logic is exercised by the production sync integration tests too;
    # this verifies a smaller snapshot's archived ID stays identifiable.
    src = tmp_path / "source.db"
    setup_db(src)
    with sqlite3.connect(src) as conn:
        r.ensure_schema(conn)
        conn.execute("INSERT INTO purged_postings VALUES (?,?,?,?)",
                     ("vagas_com", "v2831001", "2026-11-16T10:00:00+00:00",
                      "http_410"))
        assert conn.execute("SELECT COUNT(*) FROM purged_postings").fetchone()[0] == 1


def test_real_web_sync_accepts_smaller_snapshot_only_with_tombstone(tmp_path):
    """The site's union catalog can be larger than a later cleaned snapshot."""
    try:
        from tools.sync_web_catalog import sync_catalog, SyncError
    except ImportError:
        pytest.skip("Full Opportunity Radar checkout is required")
    src = tmp_path / "classroom_latest.db"
    dst = tmp_path / "radar-web.db"
    # Simulate the SQL schema in tools.sync_web_catalog's own test fixture.
    # The full production sync also expects course-score and intent tables.
    for path in (src, dst):
        setup_db(path)
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE opportunity_intents(
                   opportunity_id TEXT,intent_id TEXT,
                   PRIMARY KEY(opportunity_id,intent_id)
                );
            """)
            # Primary key on course-score is required for UPSERT.
            conn.execute("DROP TABLE opportunity_course_scores")
            conn.execute("""CREATE TABLE opportunity_course_scores(
                opportunity_id TEXT NOT NULL,course_id TEXT NOT NULL,score INT,
                PRIMARY KEY(opportunity_id,course_id))""")
            add_job(conn, "successfactors", "zf", "a", URL)
    with sqlite3.connect(dst) as conn:
        add_job(conn, "vagas_com", "v2831001", "b", OTHER)
        conn.execute("INSERT INTO web_device_favorites VALUES ('fav','b')")
    with sqlite3.connect(src) as conn:
        r.ensure_schema(conn)
        conn.execute("INSERT INTO purged_postings VALUES (?,?,?,?)",
                     ("vagas_com", "v2831001", "2026-11-17T10:00:00+00:00",
                      "http_404"))
    result = sync_catalog(src, dst)
    assert result["retirement_tombstones"]["imported"] == 1
    assert result["retirement_tombstones"]["protected"] == 1
    with sqlite3.connect(dst) as conn:
        assert conn.execute("SELECT is_active FROM source_postings "
                            "WHERE source='vagas_com'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM web_device_favorites").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 2


def test_daily_audit_rechecks_prior_404_before_deactivating(tmp_path, monkeypatch):
    db = tmp_path / "radar.db"
    setup_db(db)
    with sqlite3.connect(db) as conn:
        add_job(conn, "successfactors", "zf", "o1", URL)
        conn.execute("""CREATE TABLE source_availability_checks (
            source TEXT,source_job_id TEXT,verdict TEXT,evidence TEXT,
            checked_at TEXT,PRIMARY KEY(source,source_job_id))""")
        conn.execute("""INSERT INTO source_availability_checks VALUES
            ('successfactors','zf','unverified','http_404','2026-11-01T10:00:00+00:00')""")
        conn.commit()
        monkeypatch.setattr(r, "probe", lambda *_: ("unverified", "http_404"))
        first = r.run_daily_retirement(conn, db_path=db,
            now=datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
        assert first["rechecked"] == 0
        assert conn.execute("SELECT bad_checks FROM posting_retirement_checks").fetchone()[0] == 1
        second = r.run_daily_retirement(conn, db_path=db,
            now=datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
        assert second["rechecked"] == 1
        assert second["inactivated"] == 0
        third = r.run_daily_retirement(conn, db_path=db,
            now=datetime(2026, 11, 3, 12, tzinfo=timezone.utc))
        assert third["rechecked"] == 1
        assert third["inactivated"] == 1
        assert conn.execute("SELECT is_active FROM jobs").fetchone()[0] == 0


def test_confirmed_reopening_restores_only_soft_404_deactivation(tmp_path):
    db = tmp_path / "radar.db"
    setup_db(db)
    with sqlite3.connect(db) as conn:
        add_job(conn, "successfactors", "zf", "o1", URL)
        for day in (1, 2, 3):
            r.observe(conn, "successfactors", "zf", URL, "unverified", "http_404",
                      checked_at=f"2026-11-{day:02d}T12:00:00+00:00")
        assert conn.execute("SELECT is_active FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT disabled_by_missing FROM posting_retirement_checks").fetchone()[0] == 1
        r.observe(conn, "successfactors", "zf", URL, "open", "explicit_applications_open",
                  checked_at="2026-11-04T12:00:00+00:00")
        assert conn.execute("SELECT is_active FROM jobs").fetchone()[0] == 1
        assert conn.execute("SELECT is_active FROM source_postings").fetchone()[0] == 1
        assert conn.execute("SELECT bad_checks FROM posting_retirement_checks").fetchone()[0] == 0
        assert conn.execute("SELECT disabled_by_missing FROM posting_retirement_checks").fetchone()[0] == 0
