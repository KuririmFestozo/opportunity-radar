"""Keep the login DB stable while bringing in the latest vacancy catalog."""
import sqlite3
from pathlib import Path

import pytest

from tools.sync_web_catalog import SyncError, sync_catalog


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE opportunities (
  id TEXT PRIMARY KEY, title TEXT
);
CREATE TABLE source_postings (
  source TEXT, source_job_id TEXT, opportunity_id TEXT NOT NULL,
  is_active INTEGER NOT NULL, url TEXT,
  PRIMARY KEY(source,source_job_id),
  FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);
CREATE TABLE opportunity_course_scores (
  opportunity_id TEXT, course_id TEXT, score INT,
  PRIMARY KEY(opportunity_id,course_id),
  FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);
CREATE TABLE opportunity_intents (
  opportunity_id TEXT, intent_id TEXT,
  PRIMARY KEY(opportunity_id,intent_id),
  FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);
CREATE TABLE jobs (
  source TEXT, source_job_id TEXT, is_active INTEGER NOT NULL,
  PRIMARY KEY(source,source_job_id)
);
CREATE TABLE web_users (
  id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, created_at TEXT
);
CREATE TABLE web_device_favorites (
  id TEXT PRIMARY KEY, owner_id TEXT, opportunity_id TEXT, created_at TEXT,
  UNIQUE(owner_id,opportunity_id),
  FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);
CREATE TABLE web_device_applications (
  id TEXT PRIMARY KEY, owner_id TEXT, opportunity_id TEXT,
  status TEXT, notes TEXT, updated_at TEXT,
  UNIQUE(owner_id,opportunity_id),
  FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);
"""


def make_db(path, *, latest=False, account=False):
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO opportunities VALUES ('A','Older')" if not latest
                     else "INSERT INTO opportunities VALUES ('A','Updated')")
        conn.execute("""
          INSERT INTO source_postings VALUES ('gupy_global','123','A',1,'https://a.gupy.io/jobs/123')
        """)
        conn.execute("INSERT INTO jobs VALUES ('gupy_global','123',1)")
        conn.execute("INSERT INTO opportunity_course_scores VALUES ('A','eng',70)")
        conn.execute("INSERT INTO opportunity_intents VALUES ('A','internship')")
        if latest:
            conn.execute("INSERT INTO opportunities VALUES ('B','New job')")
            conn.execute("""
              INSERT INTO source_postings VALUES ('workday','987','B',1,'https://example.com/987')
            """)
            conn.execute("INSERT INTO jobs VALUES ('workday','987',1)")
            conn.execute("INSERT INTO opportunity_course_scores VALUES ('B','eng',95)")
            conn.execute("INSERT INTO opportunity_intents VALUES ('B','trainee')")
        if account:
            uid, username = ("bob", "bob") if latest else ("alice", "alice")
            conn.execute("INSERT INTO web_users VALUES (?,?,?,?)",
                         (uid, username, "bcrypt-hash-preserved", "2026-11-01"))
            conn.execute("INSERT INTO web_device_favorites VALUES (?,?,?,?)",
                         ("fav-"+uid, uid, "B" if latest else "A", "2026-11-01"))
            conn.execute("INSERT INTO web_device_applications VALUES (?,?,?,?,?,?)",
                         ("app-"+uid, uid, "B" if latest else "A",
                          "PLANNED", "nota privada", "2026-11-01"))


def test_upserts_latest_catalog_without_touching_login_or_favorites(tmp_path):
    src, dst = tmp_path/"classroom_latest.db", tmp_path/"radar-web.db"
    make_db(src, latest=True, account=True)
    make_db(dst, account=True)
    with sqlite3.connect(dst) as conn:
        conn.execute("""
            CREATE TABLE gupy_url_checks
                (source TEXT, source_job_id TEXT, verdict TEXT,
                 PRIMARY KEY(source,source_job_id))
        """)
        conn.execute("INSERT INTO gupy_url_checks VALUES ('gupy_global','123','closed')")
    result = sync_catalog(src, dst)
    assert result["previous_opportunities"] == 1
    assert result["opportunities"] == 2
    assert result["users"] == 1
    assert result["confirmed_closures_preserved"] == 1
    assert Path(result["backup"]).is_file()
    with sqlite3.connect(dst) as conn:
        assert conn.execute("SELECT title FROM opportunities WHERE id='A'").fetchone() == ("Updated",)
        assert conn.execute("SELECT is_active FROM source_postings "
                            "WHERE source_job_id='123'").fetchone() == (0,)
        assert conn.execute("SELECT is_active FROM jobs "
                            "WHERE source_job_id='123'").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM web_users").fetchone()[0] == 1
        assert conn.execute("SELECT username FROM web_users").fetchone() == ("alice",)
        assert conn.execute("SELECT owner_id FROM web_device_favorites").fetchone() == ("alice",)
        assert conn.execute("SELECT notes FROM web_device_applications").fetchone() == ("nota privada",)
        assert conn.execute("SELECT score FROM opportunity_course_scores "
                            "WHERE opportunity_id='B'").fetchone() == (95,)


def test_opt_in_merges_accounts_from_the_classroom_db(tmp_path):
    src, dst = tmp_path/"classroom_latest.db", tmp_path/"radar-web.db"
    make_db(src, latest=True, account=True)
    make_db(dst, account=True)
    result = sync_catalog(src, dst, include_accounts=True)
    assert result["users"] == 2
    assert result["accounts_imported"]["accounts"] == 1
    assert result["accounts_imported"]["favorites"] == 1
    with sqlite3.connect(dst) as conn:
        assert conn.execute("SELECT username FROM web_users ORDER BY username").fetchall() == [
            ("alice",), ("bob",)]
        assert conn.execute("SELECT COUNT(*) FROM web_device_favorites").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM web_device_applications").fetchone()[0] == 2


def test_account_collision_rolls_back_snapshot_merge(tmp_path):
    src, dst = tmp_path/"classroom_latest.db", tmp_path/"radar-web.db"
    make_db(src, latest=True, account=True)
    make_db(dst, account=True)
    with sqlite3.connect(dst) as conn:
        conn.execute("INSERT INTO web_users VALUES ('conflict','bob','other','now')")
    with pytest.raises(SyncError, match="mesmo usuario"):
        sync_catalog(src, dst, include_accounts=True)
    with sqlite3.connect(dst) as conn:
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM web_device_favorites").fetchone() == (1,)


def test_never_syncs_an_older_or_empty_snapshot(tmp_path):
    src, dst = tmp_path/"classroom_latest.db", tmp_path/"radar-web.db"
    make_db(src)
    make_db(dst, latest=True, account=True)
    with pytest.raises(SyncError, match="mais antigo"):
        sync_catalog(src, dst)
    with sqlite3.connect(dst) as conn:
        assert conn.execute("SELECT COUNT(*) FROM web_users").fetchone() == (1,)


def test_requires_explicit_account_import(tmp_path):
    src, dst = tmp_path/"classroom_latest.db", tmp_path/"radar-web.db"
    make_db(src, latest=True, account=True)
    make_db(dst, account=True)
    sync_catalog(src, dst)
    with sqlite3.connect(dst) as conn:
        assert conn.execute("SELECT COUNT(*) FROM web_users").fetchone() == (1,)



def test_merges_all_source_availability_evidence_without_reopening_closures(tmp_path):
    from processing.source_availability import ensure_schema as source_schema

    src, dst = tmp_path/"classroom_latest.db", tmp_path/"radar-web.db"
    make_db(src, latest=True)
    make_db(dst, account=True)

    with sqlite3.connect(src) as conn:
        source_schema(conn)
        conn.execute("""
            INSERT INTO source_availability_checks
            VALUES ('gupy_global','123','unverified','http_429','2026-11-06')
        """)
        conn.execute("""
            INSERT INTO source_availability_checks
            VALUES ('workday','987','open','explicit_applications_open','2026-11-06')
        """)
    with sqlite3.connect(dst) as conn:
        source_schema(conn)
        conn.execute("""
            INSERT INTO source_availability_checks
            VALUES ('gupy_global','123','closed','manual_confirmation','2026-11-05')
        """)

    output = sync_catalog(src, dst)
    assert output["verification_imported"] == 1
    assert output["confirmed_closures_preserved"] == 1
    with sqlite3.connect(dst) as conn:
        assert conn.execute("""
            SELECT verdict,evidence FROM source_availability_checks
            WHERE source='gupy_global'
        """).fetchone() == ("closed", "manual_confirmation")
        assert conn.execute("""
            SELECT verdict FROM source_availability_checks
            WHERE source='workday'
        """).fetchone() == ("open",)
        assert conn.execute("""
            SELECT is_active FROM source_postings WHERE source_job_id='123'
        """).fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM web_users").fetchone() == (1,)



def test_attaches_native_path_with_spaces_unicode_and_uri_reserved_chars(tmp_path):
    """The SQL parameter must be a native path, not file:///C:/... on Windows."""
    src = tmp_path / "vagas da aula #atualizadas %2026.db"
    dst = tmp_path / "site com usuários.db"
    make_db(src, latest=True)
    make_db(dst, account=True)

    original_source = src.read_bytes()
    output = sync_catalog(src, dst)

    assert output["opportunities"] == 2
    assert src.read_bytes() == original_source
    with sqlite3.connect(dst) as conn:
        assert conn.execute("SELECT COUNT(*) FROM web_users").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 2
