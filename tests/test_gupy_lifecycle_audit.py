"""Gupy lifecycle safety tests: closed pages, partial failures and reopen guards."""
import sqlite3

from collectors.gupy_global import job_from_item
from models.job import Job
from processing import gupy_lifecycle as gl
from storage.sqlite_repository import SQLiteOpportunityRepository


def example_job(source="gupy_global", job_id="123"):
    return Job(
        source=source, source_type="public_api", source_job_id=job_id,
        company="Teste", title="Estágio de engenharia", location="São Carlos",
        description="Trabalho no setor de vagas encerradas (não é um aviso).",
        url=f"https://acme.gupy.io/jobs/{job_id}?jobBoardSource=share_link",
    )


def add_job(repo, job):
    repo.upsert_posting(job, commit=False)
    repo.mark_seen_postings([job])
    repo.commit()
    repo.sync_unified_schema()


def test_gupy_global_extracts_explicit_terminal_status():
    job = job_from_item({
        "id": 123, "name": "Estágio", "jobUrl": "https://acme.gupy.io/jobs/123",
        "status": "closed", "careerPageName": "Acme",
    })
    assert gl.explicitly_closed(job)
    assert not gl.explicitly_closed(example_job())


def test_only_exact_official_urls_are_probed():
    assert gl.safe_url("https://acme.gupy.io/jobs/123?jobBoardSource=share_link") == (
        "https://acme.gupy.io/jobs/123"
    )
    for invalid in (
        "https://evil.com/jobs/123", "https://acme.gupy.io.evil.com/jobs/123",
        "http://acme.gupy.io/jobs/123", "https://acme.gupy.io:8080/jobs/123",
        "https://acme.gupy.io@evil.com/jobs/123",
        "https://acme.gupy.io/profile", "file:///etc/passwd",
    ):
        assert gl.safe_url(invalid) is None


def test_exact_closed_banner_but_not_description_or_script():
    assert gl.explicit_page_closure("<main><h2>Esta vaga foi encerrada.</h2></main>")
    assert gl.explicit_page_closure("<main><p>Inscrições encerradas</p></main>")
    assert not gl.explicit_page_closure("""
        <main><h2>Estágio</h2><p>Atuação no setor de vagas encerradas.</p>
        <script>var message='Esta vaga foi encerrada';</script></main>
    """)
    assert not gl.explicit_page_closure("<p>Esta vaga está aberta para inscrição.</p>")


def test_http_errors_never_count_as_closed(monkeypatch):
    class Response:
        status_code = 404
        headers = {"Content-Type": "text/html"}
        text = "<h2>Esta vaga foi encerrada</h2>"
    monkeypatch.setattr(gl.requests, "get", lambda *a, **k: Response())
    assert gl.probe_url("https://acme.gupy.io/jobs/123") == ("unknown", "http_404")
    Response.status_code = 429
    assert gl.probe_url("https://acme.gupy.io/jobs/123") == ("unknown", "http_429")
    Response.status_code = 200
    assert gl.probe_url("https://acme.gupy.io/jobs/123") == ("closed", "explicit_closed_banner")


def test_audit_marks_only_confirmed_closures_and_updates_shadow(tmp_path, monkeypatch):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repo:
        closed, blocked = example_job(job_id="100"), example_job(job_id="200")
        add_job(repo, closed)
        add_job(repo, blocked)
        monkeypatch.setattr(gl, "probe_url", lambda url:
                            ("closed", "explicit_closed_banner") if url.endswith("/100")
                            else ("unknown", "http_503"))
        stats = repo.audit_gupy(limit=2, workers=1)
        assert stats == {"checked": 2, "closed": 1, "unknown": 1, "inactivated": 1}
        repo.sync_unified_schema()
        results = repo._store.conn.execute(
            "SELECT source_job_id,is_active,missing_since,inactive_at "
            "FROM jobs ORDER BY source_job_id"
        ).fetchall()
        assert [row["is_active"] for row in results] == [0, 1]
        assert results[0]["missing_since"] and results[0]["inactive_at"]
        relational = repo._store.conn.execute(
            "SELECT is_active FROM source_postings WHERE source_job_id='100'"
        ).fetchone()
        assert relational["is_active"] == 0
        assert ("gupy_global", "100") in repo.gupy_closed_keys()

        # The next global search may still return a stale listing. Never
        # reactivate a posting verified closed on its own official page.
        listed, explicit, counts = gl.filter_discoveries([closed, blocked],
                                                         repo.gupy_closed_keys())
        assert [job.source_job_id for job in listed] == ["200"]
        assert explicit == set() and counts["previously_closed"] == 1


def test_dry_run_does_not_inactivate_or_record_url_checks(tmp_path, monkeypatch):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repo:
        add_job(repo, example_job())
        monkeypatch.setattr(gl, "probe_url",
                            lambda url: ("closed", "explicit_closed_banner"))
        stats = repo.audit_gupy(limit=1, workers=1, apply=False)
        assert stats["closed"] == 1 and stats["inactivated"] == 0
        assert repo._store.conn.execute(
            "SELECT is_active FROM jobs WHERE source_job_id='123'"
        ).fetchone()["is_active"] == 1
        assert repo.gupy_closed_keys() == set()


def test_explicit_source_closure_is_filtered_before_upsert(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repo:
        add_job(repo, example_job())
        closed = example_job()
        closed.metadata["gupy_status"] = "canceled"
        kept, reported, counts = gl.filter_discoveries([closed], set())
        assert not kept and reported == {("gupy_global", "123")}
        assert counts["explicit"] == 1
        repo.mark_gupy_closed(reported)
        repo.commit()
        repo.sync_unified_schema()
        assert repo._store.conn.execute(
            "SELECT is_active FROM jobs WHERE source_job_id='123'"
        ).fetchone()["is_active"] == 0


def test_unverified_absence_cannot_inactivate_gupy(tmp_path):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repo:
        add_job(repo, example_job())
        life = repo.reconcile_scope("gupy_global", [], coverage="partial")
        assert life["skipped"]
        assert repo._store.conn.execute(
            "SELECT is_active FROM jobs WHERE source_job_id='123'"
        ).fetchone()["is_active"] == 1


# Reported closed opportunities from real Gupy candidate pages (Nov 2026).
COPLANA_URL = "https://coplana.gupy.io/job/eyJqb2JJZCI6MTIzMTQwNzcsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=?jobBoardSource=gupy_portal"
SIDI_URL = "https://sidi.gupy.io/job/eyJqb2JJZCI6MTIyNzA4ODcsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=?jobBoardSource=gupy_portal"


def test_real_gupy_portal_urls_extract_the_expected_ids():
    assert gl.gupy_job_id(COPLANA_URL) == "12314077"
    assert gl.gupy_job_id(SIDI_URL) == "12270887"
    assert gl.safe_url(COPLANA_URL) == COPLANA_URL.split("?")[0]
    assert gl.safe_url(SIDI_URL) == SIDI_URL.split("?")[0]


def test_real_gupy_english_closure_banners_and_paused_status():
    assert gl.explicit_page_closure(
        "<div class='status'><span>Applications closed</span></div>"
        "<h1>Estagiário (a) - Engenharia Industrial</h1>"
        "<p>Esta vaga está na equipe industrial.</p>"
    )
    assert gl.explicit_page_closure(
        "<div>This position has been paused by the company.</div>"
        "<span>Applications closed</span>"
    )
    assert not gl.explicit_page_closure(
        "<h2>Applications OPEN</h2><p>Experience with applications closed "
        "in a previous project.</p><script>var text='Applications closed'</script>"
    )


def test_invalid_encoded_urls_are_never_fetched():
    assert gl.gupy_job_id("https://example.com/job/eyJqb2JJZCI6MTIzMTQwNzc=") is None
    assert gl.gupy_job_id("https://sidi.gupy.io/job/AAAAAAAAAAAAAAAB=") is None
    assert gl.gupy_job_id("https://sidi.gupy.io/job/eyJqb2JJZCI6Mn0=") is None
    assert gl.gupy_job_id("https://sidi.gupy.io/job/eyJqb2JJZCI6MTIzLCJzb3VyY2UiOiJldmlsIn0=") is None


def test_audits_reported_encoded_urls_regardless_of_scan_order(tmp_path, monkeypatch):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repo:
        job1 = example_job(job_id="12314077")
        job1.url = COPLANA_URL
        job2 = example_job(job_id="12270887")
        job2.url = SIDI_URL
        unrelated = example_job(job_id="999999")
        for job in (unrelated, job1, job2):
            add_job(repo, job)
        probed = []
        def fake_probe(url):
            probed.append(url)
            return ("closed", "explicit_closed_banner")
        monkeypatch.setattr(gl, "probe_url", fake_probe)
        stats = repo.audit_gupy(limit=1, workers=1, urls=[COPLANA_URL, SIDI_URL])
        assert stats["checked"] == 2
        assert stats["closed"] == 2
        assert stats["inactivated"] == 2
        assert set(probed) == {gl.safe_url(COPLANA_URL), gl.safe_url(SIDI_URL)}
        assert repo._store.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active=0"
        ).fetchone()[0] == 2
        assert repo._store.conn.execute(
            "SELECT COUNT(*) FROM jobs"
        ).fetchone()[0] == 3
        repo.sync_unified_schema()
        assert repo._store.conn.execute(
            "SELECT COUNT(*) FROM source_postings WHERE is_active=0"
        ).fetchone()[0] == 2


def test_unmatched_specific_job_is_not_assumed_to_be_closed(tmp_path, monkeypatch):
    with SQLiteOpportunityRepository(tmp_path / "radar.db") as repo:
        add_job(repo, example_job())
        monkeypatch.setattr(gl, "probe_url", lambda url: ("closed", "explicit_closed_banner"))
        stats = repo.audit_gupy(urls=[COPLANA_URL], apply=True)
        assert stats["checked"] == 0 and stats["inactivated"] == 0
        assert repo._store.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active=1"
        ).fetchone()[0] == 1


def test_manual_closed_url_requires_apply_and_only_updates_matching_posting(tmp_path, monkeypatch):
    import sys
    from tools import audit_gupy_lifecycle as cli
    path = tmp_path / "radar-web.db"
    with SQLiteOpportunityRepository(path) as repo:
        match = example_job(job_id="12314077")
        match.url = COPLANA_URL
        add_job(repo, match)
        add_job(repo, example_job(job_id="999"))
    monkeypatch.setattr(sys, "argv", [
        "audit_gupy_lifecycle", "--db", str(path),
        "--confirm-closed-url", COPLANA_URL, "--apply",
    ])
    assert cli.main() == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
        assert conn.execute("SELECT is_active FROM jobs WHERE source_job_id='12314077'").fetchone()[0] == 0
        assert conn.execute("SELECT is_active FROM jobs WHERE source_job_id='999'").fetchone()[0] == 1
        assert conn.execute("SELECT is_active FROM source_postings WHERE source_job_id='12314077'").fetchone()[0] == 0
    assert list((tmp_path / "backups").glob("*.db"))


def test_manual_closed_url_without_apply_refuses_to_change_data(tmp_path, monkeypatch):
    import sys
    from tools import audit_gupy_lifecycle as cli
    path = tmp_path / "radar-web.db"
    with SQLiteOpportunityRepository(path) as repo:
        match = example_job(job_id="12270887")
        match.url = SIDI_URL
        add_job(repo, match)
    monkeypatch.setattr(sys, "argv", [
        "audit_gupy_lifecycle", "--db", str(path),
        "--confirm-closed-url", SIDI_URL,
    ])
    import pytest
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT is_active FROM jobs").fetchone()[0] == 1



def test_gupy_probe_reuses_structured_deadline_classifier(monkeypatch):
    class Response:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        text = """<h1>Estágio</h1><script type="application/ld+json">
        {"@type":"JobPosting","validThrough":"2020-10-30T23:59:59-03:00"}
        </script>"""
    monkeypatch.setattr(gl.requests, "get", lambda *args, **kwargs: Response())
    assert gl.probe_url("https://a.gupy.io/jobs/123") == (
        "closed", "jobposting_valid_through_2020-10-30"
    )
