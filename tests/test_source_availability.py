"""Availability must distinguish open, closed, unverified and unchecked."""
from datetime import date
import sqlite3

import pytest

from processing import source_availability as sa
from tools import audit_source_availability as cli

LINKS = {
    "99jobs": "https://99jobs.com/kabum/jobs/512644-cientista-de-dados",
    "bettha": "https://admin-vagas.bettha.com/hotsite/supplychainwerfen3149",
    "bettha_2": "https://admin-vagas.bettha.com/hotsite/Estagio-Logistica-Importacao-Exportacao-Aromas",
    "cargill": "https://careers.cargill.com/en/job/bengaluru/software-engineer-intern/23251/102151489616",
    "cia_estagios": "https://www.ciadeestagios.com.br/vagas/wabtec/",
    "iel": "https://carreiras.iel.org.br/DF/vaga/vagas-destinadas-a-aprendizagem-de-cursos/24614/recursos-humanos",
}


def fixture(db):
    with sqlite3.connect(db) as conn:
        conn.executescript("""
          CREATE TABLE opportunities (id TEXT PRIMARY KEY);
          CREATE TABLE source_postings (
            source TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            opportunity_id TEXT NOT NULL,
            url TEXT NOT NULL,
            is_active INTEGER NOT NULL,
            last_seen_at TEXT,
            inactive_at TEXT,
            last_checked_at TEXT,
            PRIMARY KEY(source,source_job_id)
          );
          CREATE TABLE jobs (
            source TEXT NOT NULL,
            source_job_id TEXT NOT NULL,
            is_active INTEGER NOT NULL,
            inactive_at TEXT,
            last_checked_at TEXT,
            PRIMARY KEY(source,source_job_id)
          );
          CREATE TABLE web_users (id TEXT PRIMARY KEY, username TEXT NOT NULL);
          INSERT INTO web_users VALUES ('1','conta_local');
        """)
        for i, (key, url) in enumerate(LINKS.items()):
            source = "bettha" if key.startswith("bettha") else key
            conn.execute("INSERT INTO opportunities VALUES (?)", (str(i),))
            conn.execute(
                "INSERT INTO source_postings VALUES (?,?,?,?,1,'2026-11-06',NULL,NULL)",
                (source, key, str(i), url),
            )
            conn.execute("INSERT INTO jobs VALUES (?,?,1,NULL,NULL)", (source, key))


def test_expected_six_real_links_are_safe_for_auditing():
    for key, url in LINKS.items():
        src = "bettha" if key.startswith("bettha") else key
        assert sa.safe_url(src, url) is not None
        assert sa.normalize_url(url) == sa.normalize_url(url + "?utm_source=example")
    assert sa.safe_url("cargill", "https://evil.com/en/job/123") is None
    assert sa.safe_url("bettha", "https://admin-vagas.bettha.com.evil.org/hotsite/123") is None
    assert sa.safe_url("iel", "file:///etc/passwd") is None


def test_explicit_closure_and_real_application_deadline():
    assert sa.classify_html("99jobs", "<h2>Inscrições encerradas</h2>") == (
        "closed", "explicit_closed_message"
    )
    assert sa.classify_html("cia_estagios", (
        "<h1>Programa de Estágio Wabtec 2027</h1>"
        "<p>As inscrições vão até 30/10/2026. Candidate-se.</p>"
        "<div>Veja todas as informações do programa de estágio!</div>"
    ), today=date(2026, 11, 6)) == ("closed", "deadline_2026-10-30")
    assert sa.classify_html("cia_estagios", (
        "<h1>Programa Wabtec 2027</h1><p>Inscrições até 30/10</p>"
        "<p>Faça o seu cadastro e participe da seleção!</p>"
    ), today=date(2026, 11, 6))[0] == "unverified"
    assert sa.classify_html("cia_estagios", (
        "<h1>Programa Wabtec 2027</h1><p>Inscrições até 30/10/2027</p>"
        "<p>Faça o seu cadastro e participe da seleção!</p>"
    ), today=date(2026, 11, 6))[0] != "closed"


def test_description_and_application_button_do_not_prove_open():
    assert sa.classify_html("99jobs", (
        "<h1>Cientista de Dados</h1><p>Processo de inscrição pode ocorrer "
        "conforme disponibilidade da empresa; candidate-se.</p>"
    ))[0] == "unverified"
    assert sa.classify_html("iel", (
        "<h1>Recursos Humanos</h1><p>O candidato precisa fazer login e se candidate.</p>"
    )) == ("unverified", "application_requires_login")
    assert sa.classify_html("bettha", "<script>Inscrições abertas!</script>")[0] == "unverified"
    assert sa.classify_html("bettha", (
        "<h1>Estágio em Logística</h1><div>Inscrições abertas.</div>"
    ))[0] == "unverified"  # generic div/button is not source-verified
    assert sa.classify_html("99jobs", (
        "<h1>Estágio</h1><p>Inscrições abertas</p>"
        "<p>A inscrição estará disponível até o dia informado pela empresa.</p>"
    ))[0] == "open"


def test_http_3xx_and_404_are_unverified_not_closed(monkeypatch):
    class Response:
        status_code = 302
        headers = {"Content-Type": "text/html"}
        text = "Applications closed"
    monkeypatch.setattr(sa.requests, "get", lambda *a, **k: Response())
    assert sa.probe("cargill", LINKS["cargill"]) == (
        "unverified", "redirect_from_job"
    )
    Response.status_code = 404
    assert sa.probe("cargill", LINKS["cargill"]) == (
        "unverified", "http_404"
    )
    Response.status_code = 200
    Response.text = "<h2>Vaga encerrada</h2>"
    assert sa.probe("cargill", LINKS["cargill"])[0] == "closed"


def test_database_overlay_tracks_status_without_dropping_user_data(tmp_path):
    db = tmp_path / "radar-web.db"
    fixture(db)
    with sqlite3.connect(db) as conn:
        sa.ensure_schema(conn)
        assert sa.apply_result(conn, "cargill", "cargill",
                               "unverified", "redirect_from_job") == 0
        assert sa.apply_result(conn, "cia_estagios", "cia_estagios",
                               "closed", "deadline_2026-10-30") == 1
        assert sa.apply_result(conn, "99jobs", "99jobs",
                               "open", "explicit_applications_open") == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM source_postings WHERE is_active=0"
        ).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM web_users").fetchone()[0] == 1
        assert conn.execute(
            "SELECT verdict FROM source_availability_checks "
            "WHERE source='cargill'"
        ).fetchone()[0] == "unverified"
        assert conn.execute("SELECT COUNT(*) FROM source_postings").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 6
        assert ("cia_estagios", "cia_estagios") in sa.closed_posting_keys(conn)


def test_specific_url_query_and_dry_run_never_change_db(tmp_path, monkeypatch):
    db = tmp_path / "radar-web.db"
    fixture(db)
    monkeypatch.setattr(cli, "probe", lambda source, url: (
        "unverified", "redirect_from_job"
    ))
    before = db.read_bytes()
    output = cli.run(db, urls=[LINKS["cargill"]], apply=False)
    assert output["unverified"] == 1
    assert db.read_bytes() == before
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name='source_availability_checks'"
        ).fetchone()[0] == 0


def test_specific_url_apply_creates_backup_and_marks_unverified(tmp_path, monkeypatch):
    db = tmp_path / "radar-web.db"
    fixture(db)
    monkeypatch.setattr(cli, "probe", lambda source, url: (
        "unverified", "no_confirmed_application_state"
    ))
    stats = cli.run(db, urls=[LINKS["iel"]], apply=True)
    assert stats["unverified"] == 1 and stats["inactivated"] == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT verdict FROM source_availability_checks WHERE source='iel'"
        ).fetchone()[0] == "unverified"
        assert conn.execute("SELECT is_active FROM source_postings "
                            "WHERE source='iel'").fetchone()[0] == 1
    assert list((tmp_path / "backups").glob("*.db"))


def test_closed_is_not_reopened_by_unverified_decision(tmp_path):
    db = tmp_path / "radar-web.db"
    fixture(db)
    with sqlite3.connect(db) as conn:
        sa.apply_result(conn, "bettha", "bettha", "closed", "explicit_closed_message")
        assert sa.apply_result(conn, "bettha", "bettha",
                               "unverified", "http_429") == 0
        assert ("bettha", "bettha") in sa.closed_posting_keys(conn)


def test_filter_confirmed_closed_only():
    class Job:
        def __init__(self, source, id):
            self.source = source
            self.source_job_id = id
    jobs = [Job("bettha", "a"), Job("iel", "b")]
    kept, filtered = sa.suppress_confirmed_closed(jobs, {("bettha", "a")})
    assert [item.source for item in kept] == ["iel"]
    assert filtered == 1
