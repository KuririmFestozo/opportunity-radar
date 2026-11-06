"""Regression cases reported Nov 6: Vagas.com, ZF and Gupy URLs."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from processing import source_availability as availability
from processing.gupy_lifecycle import gupy_job_id
from tools.audit_source_availability import run

VAGAS_MAINTENANCE = "https://www.vagas.com.br/vagas/v2831001/estagio-em-manutencao"
ZF = "https://jobs.zf.com/job/Araraquara-Estágio-Recursos-Humanos-SP-14800-655/1431252033/"
VAGAS_LAB = "https://www.vagas.com.br/vagas/v2831206/estagio-em-laboratorio"
SANTA = "https://santaclaragrupo.gupy.io/job/eyJqb2JJZCI6MTIwNzE4MjYsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=?jobBoardSource=gupy_portal"
BELGO = "https://belgo.gupy.io/job/eyJqb2JJZCI6MTI0MjQxMDcsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=?jobBoardSource=gupy_portal"
MAISPET = "https://vagasmaispetoficial.gupy.io/job/eyJqb2JJZCI6MTI0NDQxOTEsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=?jobBoardSource=gupy_portal"
CLOSED = [VAGAS_MAINTENANCE, ZF, VAGAS_LAB, SANTA, BELGO]


def fixture(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE source_postings(
              source TEXT, source_job_id TEXT, url TEXT,
              is_active INT NOT NULL, inactive_at TEXT, last_checked_at TEXT,
              opportunity_id TEXT, last_seen_at TEXT,
              PRIMARY KEY(source,source_job_id));
            CREATE TABLE jobs(source TEXT, source_job_id TEXT,
              is_active INT NOT NULL, inactive_at TEXT, last_checked_at TEXT,
              PRIMARY KEY(source,source_job_id));
            CREATE TABLE web_users(id TEXT PRIMARY KEY, username TEXT, password_hash TEXT);
            CREATE TABLE web_device_favorites(
              id TEXT PRIMARY KEY, owner_id TEXT, opportunity_id TEXT);
            CREATE TABLE web_device_applications(
              id TEXT PRIMARY KEY, owner_id TEXT, opportunity_id TEXT, notes TEXT);
            INSERT INTO web_users VALUES ('owner','leandro','$2a$12$do-not-touch');
            INSERT INTO web_device_favorites VALUES ('fav','owner','opp-1');
            INSERT INTO web_device_applications VALUES ('app','owner','opp-1','minha nota');
        """)
        # The Santa Clara job may have an older /jobs/123 URL stored in
        # the local SQLite, while the user has the redesigned encoded URL.
        cases = [
            ("vagas_com", "v2831001", VAGAS_MAINTENANCE),
            ("successfactors", "zf-1431252033", ZF),
            ("vagas_com", "v2831206", VAGAS_LAB),
            ("gupy_global", "12071826",
             "https://santaclaragrupo.gupy.io/jobs/12071826"),
            ("gupy_global", "12424107", BELGO),
            ("gupy_global", "12444191", MAISPET),
        ]
        for i, (source, job_id, url) in enumerate(cases):
            db.execute(
                "INSERT INTO source_postings VALUES (?,?,?,?,?,?,?,?)",
                (source, job_id, url, 1, None, None, f"opp-{i}", "2026-11-06")
            )
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?)",
                       (source, job_id, 1, None, None))


def test_successfactors_zf_detects_formal_position_filled():
    assert availability.safe_url("successfactors", ZF) is not None
    assert availability.classify_html("successfactors",
        "<main><div><p>Sorry, this position has been filled.</p></div>"
        "<h1>Estágio Recursos Humanos</h1></main>"
    ) == ("closed", "explicit_closed_message")
    assert availability.safe_url("successfactors",
        "https://jobs.zf.com.evil.org/job/123") is None
    assert availability.classify_html("successfactors",
        "<h1>Estágio RH</h1><p>Learn about positions that have been filled"
        " during the year.</p>"
    )[0] == "unverified"


def test_vagas_com_descriptions_do_not_prove_application_is_open_or_closed():
    description = ("<h1>Estágio em Manutenção</h1>"
                   "<p>Atualizar os cadastros de equipamentos no sistema.</p>"
                   "<p>Candidate-se gratuitamente pelo Vagas.com.</p>")
    assert availability.classify_html("vagas_com", description)[0] == "unverified"


def test_gupy_new_link_is_matched_to_old_stored_url_by_numeric_id(tmp_path):
    db = tmp_path / "radar-web.db"
    fixture(db)
    with sqlite3.connect(db) as conn:
        found, missing = availability.select_postings(
            conn, urls=[SANTA, BELGO, MAISPET]
        )
    assert not missing
    assert {(row[0], row[1]) for row in found} == {
        ("gupy_global", "12071826"),
        ("gupy_global", "12424107"),
        ("gupy_global", "12444191"),
    }
    assert gupy_job_id(SANTA) == "12071826"


def test_manual_closures_and_unavailable_link_keep_all_history_and_accounts(tmp_path, monkeypatch):
    db = tmp_path / "radar-web.db"
    fixture(db)
    # User-confirmed status should never trigger a live network request.
    monkeypatch.setattr("tools.audit_source_availability.probe",
                        lambda *args: (_ for _ in ()).throw(
                            AssertionError("Unexpected network request")))
    stats = run(db, confirm_closed_urls=CLOSED,
                flag_unavailable_urls=[MAISPET], apply=True)
    assert stats["closed"] == 5
    assert stats["unverified"] == 1
    assert stats["inactivated"] == 5
    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as old:
        assert old.execute("SELECT COUNT(*) FROM source_postings WHERE is_active=1").fetchone()[0] == 6
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_postings").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM source_postings WHERE is_active=0").fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active=0").fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM web_users").fetchone()[0] == 1
        assert conn.execute("SELECT password_hash FROM web_users").fetchone()[0] == "$2a$12$do-not-touch"
        assert conn.execute("SELECT COUNT(*) FROM web_device_favorites").fetchone()[0] == 1
        assert conn.execute("SELECT notes FROM web_device_applications").fetchone()[0] == "minha nota"
        assert conn.execute(
            "SELECT verdict,evidence FROM source_availability_checks "
            "WHERE source='gupy_global' AND source_job_id='12444191'"
        ).fetchone() == ("unverified", "user_reported_unavailable_link")
        assert conn.execute(
            "SELECT is_active FROM source_postings "
            "WHERE source='gupy_global' AND source_job_id='12444191'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM source_availability_checks WHERE verdict='closed'"
        ).fetchone()[0] == 5


def test_manual_override_requires_apply_and_rejects_conflicts(tmp_path):
    db = tmp_path / "radar-web.db"
    fixture(db)
    before = db.read_bytes()
    with pytest.raises(ValueError, match="requer --apply"):
        run(db, confirm_closed_urls=[ZF])
    with pytest.raises(ValueError, match="contraditorias"):
        run(db, confirm_closed_urls=[BELGO],
            flag_unavailable_urls=[BELGO], apply=True)
    assert db.read_bytes() == before


def test_no_match_does_not_modify_any_posting(tmp_path):
    db = tmp_path / "radar-web.db"
    fixture(db)
    stats = run(db, confirm_closed_urls=[
        "https://www.vagas.com.br/vagas/v999999999/absent"
    ], apply=True)
    assert stats["inactivated"] == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_postings WHERE is_active=0").fetchone()[0] == 0
