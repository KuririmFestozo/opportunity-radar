"""Ensure availability coverage stays in sync with the collector registry."""
import ast
from collections import Counter
from pathlib import Path
import sqlite3

from processing import source_availability as sa

ROOT = Path(__file__).resolve().parents[1]


def test_all_literal_job_sources_have_a_verifier_family():
    # Never silently ignore sources when a new collector is introduced.
    literal_sources = set()
    for path in (ROOT / "collectors").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (keyword.arg == "source"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)):
                    literal_sources.add(keyword.value.value)
    assert literal_sources <= sa.SUPPORTED, (
        f"Source families without an availability implementation: "
        f"{sorted(literal_sources - sa.SUPPORTED)}"
    )


def test_all_known_source_families_appear_in_coverage_report(tmp_path):
    db = tmp_path / "all_sources.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE source_postings
                (source TEXT, source_job_id TEXT, url TEXT,
                 is_active INTEGER, last_seen_at TEXT,
                 PRIMARY KEY(source,source_job_id))
        """)
        for index, source in enumerate(sorted(sa.SUPPORTED)):
            conn.execute(
                "INSERT INTO source_postings VALUES (?,?,?,?,?)",
                (source, str(index), "https://example.com/job/" + str(index), 1, "2026-11-01"),
            )
        coverage = sa.source_coverage(conn)
        assert {row["source"] for row in coverage} == set(sa.SUPPORTED)
        assert all(row["historical"] == row["active"] == row["unchecked"] == 1
                   for row in coverage)
        assert all(row["verified_open"] == row["verified_closed"] == 0
                   for row in coverage)


def test_all_sources_receive_one_audit_slot_when_budget_allows(tmp_path):
    db = tmp_path / "all_sources.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE source_postings
                (source TEXT, source_job_id TEXT, url TEXT,
                 is_active INTEGER, last_seen_at TEXT,
                 PRIMARY KEY(source,source_job_id))
        """)
        for source in sa.SUPPORTED:
            for i in range(3):
                conn.execute(
                    "INSERT INTO source_postings VALUES (?,?,?,?,?)",
                    (source, str(i), "https://example.com/" + str(i),
                     1, f"2026-11-0{i+1}"),
                )
        candidates, unmatched = sa.select_postings(
            conn, limit=len(sa.SUPPORTED)
        )
        assert not unmatched
        assert {row[0] for row in candidates} == sa.SUPPORTED
        assert all(count == 1 for count in Counter(
            row[0] for row in candidates
        ).values())


def test_urls_reject_unsafe_hosts_across_vendor_families():
    valid = {
        "workday": "https://hitachi.wd1.myworkdayjobs.com/en-US/hitachi/job/123",
        "smartrecruiters": "https://jobs.smartrecruiters.com/BoschGroup/123",
        "lever": "https://jobs.lever.co/shieldai/1234",
        "ashby": "https://jobs.ashbyhq.com/etched/123",
        "inhire": "https://db1.inhire.app/vagas/123/estagio",
        "izirh": "https://embraer.izirh.io/visualizar-vaga/123",
        "successfactors": "https://jobs.sap.com/job/Sao-Paulo/1234/",
        "totvs": "https://atracaodetalentos.totvs.app/vaga/123",
        "teamtailor": "https://careers.tecumseh.com/jobs/123",
        "eightfold": "https://jobs.amdocs.com/careers/job/123",
        "gupy_global": "https://sidi.gupy.io/jobs/12270887",
        "vagas_com": "https://www.vagas.com.br/vagas/v123",
        "nube": "https://www.nube.com.br/estudantes/vagas/123",
        "walljobs": "https://app.walljobs.com.br/vagas/123",
    }
    for source, url in valid.items():
        assert sa.safe_url(source, url) is not None, (source, url)
        assert sa.safe_url(source, url.replace("https://", "http://")) is None
        assert sa.safe_url(source, url.replace("https://", "https://evil.com/")) is None
        assert sa.safe_url(source, url.replace("/", ".evil.com/", 3)) is None


def test_disabled_legacy_collectors_remain_auditable():
    assert {"ciee", "cia_talentos", "gupy_public"} <= sa.SUPPORTED
