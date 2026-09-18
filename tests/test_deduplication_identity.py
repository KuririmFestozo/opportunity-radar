from dataclasses import replace
from itertools import permutations
import json

import pytest

from api import nearby
from models.job import Job
from processing.deduplicate import (
    canonical_job_url, deduplicate_jobs, deduplicate_source_jobs,
    fingerprint, source_identities, source_references,
)
from storage.job_store import JobStore, raw_content_hash


def job(identifier="1", **overrides):
    values = dict(source="gupy_global", source_job_id=identifier,
                  company="Empresa", title="Programa de Estágio", location="São Carlos - SP",
                  url=f"https://empresa.gupy.io/jobs/{identifier}")
    values.update(overrides)
    return Job(**values)


def test_same_company_title_city_with_different_ids_and_urls_remain_separate():
    assert len(deduplicate_jobs([job("1"), job("2")])) == 2


def test_same_named_program_in_different_years_remains_separate():
    assert len(deduplicate_jobs([
        job("1", published_at="2026-01-01"), job("2", published_at="2027-01-01"),
    ])) == 2


@pytest.mark.parametrize("metadata", [{"department": "Vendas"}, {"unit": "Unidade B"}])
def test_distinct_departments_or_units_remain_separate(metadata):
    assert len(deduplicate_jobs([job("1"), job("2", metadata=metadata)])) == 2


def test_cross_source_textual_similarity_and_unscoped_external_id_are_insufficient():
    first = job("1", metadata={"native_job_id": "42"})
    second = job("2", source="successfactors", metadata={"native_job_id": "42"})
    assert len(deduplicate_jobs([first, second])) == 2


def test_exact_identity_overrides_superficial_text_and_keeps_all_original_urls():
    first = job("1")
    rich = job("1", title="PROGRAMA DE ESTAGIO", description="Descrição completa",
               url=first.url + "?utm_source=portal")
    before = [first.to_dict(), rich.to_dict()]
    for dedup in (deduplicate_source_jobs, deduplicate_jobs):
        result = dedup([first, rich, first])
        assert len(result) == 1 and result[0].description == rich.description
        assert result[0].metadata["source_references"] == source_references(first, rich)
        assert len(result[0].metadata["source_references"]) == 2
    assert [first.to_dict(), rich.to_dict()] == before


def test_same_url_from_two_sources_is_catalog_only_deduplication():
    first = job("1")
    second = replace(first, source="99jobs", source_job_id="external-1", title="PROGRAMA DE ESTAGIO")
    assert len(deduplicate_source_jobs([first, second])) == 2
    result = deduplicate_jobs([first, second])
    assert len(result) == 1
    assert source_identities(result[0]) == {("gupy_global", "1"), ("99jobs", "external-1")}
    assert deduplicate_jobs(result)[0].to_dict() == result[0].to_dict()


def test_distinct_ids_of_same_source_are_not_merged_by_shared_url():
    assert len(deduplicate_jobs([job("1"), job("2", url=job("1").url)])) == 2


def test_title_normalization_preserves_distinct_programming_languages():
    first = job(title="C++ Developer")
    second = replace(first, source="other", title="C# Developer")
    assert len(deduplicate_jobs([first, second])) == 2


def test_publication_dates_with_different_timezone_signs_are_not_equivalent():
    first = job(published_at="2026-01-01T00:00:00+03:00")
    second = replace(first, source="other", published_at="2026-01-01T00:00:00-03:00")
    assert len(deduplicate_jobs([first, second])) == 2


@pytest.mark.parametrize("updates", [
    {"published_at": "2027-01-01"}, {"location": "Manaus - AM"},
    {"company": "Outra empresa"}, {"title": "Outro programa"},
    {"workplace_type": "remote"}, {"employment_type": "trainee"},
    {"description": "Departamento de vendas"},
    {"metadata": {"department": "Vendas"}}, {"metadata": {"unit": "Unidade B"}},
])
def test_shared_url_cannot_override_conflicting_evidence(updates):
    first = job("1", published_at="2026-01-01", workplace_type="onsite",
                employment_type="internship", description="Departamento financeiro",
                metadata={"department": "Financeiro", "unit": "Unidade A"})
    second = replace(first, source="99jobs", source_job_id="external-1", **updates)
    assert len(deduplicate_jobs([first, second])) == 2


@pytest.mark.parametrize("url", ["https://example.com/", "https://example.com/careers", "https://example.com/jobs/search", "", "javascript:alert(1)"])
def test_generic_or_invalid_urls_are_not_identity_evidence(url):
    assert len(deduplicate_jobs([job("1", url=url), job("2", source="other", url=url)])) == 2


def test_tracking_is_removed_without_changing_original_references():
    first = job("1", url="https://EXAMPLE.com/jobs/12?jobId=12&utm_source=feed&lang=pt#details")
    second = job("2", source="99jobs", url="https://example.com/jobs/12?jobId=12&lang=pt#details")
    assert canonical_job_url(first.url) == second.url
    result = deduplicate_jobs([first, second])
    assert len(result) == 1
    assert {r["url"] for r in source_references(result[0])} == {first.url, second.url}


@pytest.mark.parametrize("suffix_a,suffix_b", [
    ("?jobId=1", "?jobId=2"), ("?id=1", "?id=2"),
    ("?department=A", "?department=B"), ("#job-1", "#job-2"),
    ("?ref=1", "?ref=2"), ("?id=1&id=2", "?id=2&id=1"),
])
def test_identity_queries_unknown_parameters_and_fragments_are_preserved(suffix_a, suffix_b):
    base = "https://example.com/jobs/12"
    assert canonical_job_url(base + suffix_a) != canonical_job_url(base + suffix_b)
    assert len(deduplicate_jobs([job(url=base + suffix_a), job("2", source="other", url=base + suffix_b)])) == 2


def test_sparse_record_does_not_bridge_conflicting_dates_in_any_order():
    first = job("1", published_at="2026-01-01")
    second = replace(first, source="other", published_at="2027-01-01")
    sparse = replace(first, source="third", published_at=None)
    for order in permutations([first, second, sparse]):
        assert len(deduplicate_jobs(list(order))) == 2


def test_consolidation_keeps_date_evidence_across_pipeline_stages():
    first = job("1", published_at="2026-01-01")
    sparse = replace(first, source="other", published_at=None, description="x" * 200)
    merged = deduplicate_jobs([first, sparse])[0]
    assert merged.published_at == first.published_at
    later = replace(first, source="third", published_at="2027-01-01")
    assert len(deduplicate_jobs([merged, later])) == 2


def test_prior_merge_cannot_hide_conflicting_ids_from_same_source():
    first = job("1")
    second = replace(first, source="other", description="Mais detalhes")
    merged = deduplicate_jobs([first, second])[0]
    conflicting = replace(first, source_job_id="2")
    assert len(deduplicate_jobs([merged, conflicting])) == 2


def test_missing_ids_and_urls_are_not_collapsed_as_exact_duplicates():
    first = job("", url="")
    second = job("", url="")
    assert len(deduplicate_source_jobs([first, second])) == 2
    assert len(deduplicate_jobs([first, second])) == 2


def test_fingerprint_tracks_native_identity_not_mutable_job_text():
    assert fingerprint(job()) == fingerprint(job(title="Novo título", location="Outra cidade"))
    assert fingerprint(job("1")) != fingerprint(job("2"))


def test_references_survive_json_and_sqlite_without_changing_incremental_hash(tmp_path):
    first = job("1")
    alternate = replace(first, url=first.url + "?utm_source=feed")
    consolidated = deduplicate_source_jobs([first, alternate])[0]
    assert raw_content_hash(consolidated) == raw_content_hash(first)
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(first, commit=True)
        prepared, status, needed = store.prepare(consolidated)
        assert (status, needed) == ("unchanged", False)
        store.commit()
        restored = Job(**json.loads(json.dumps(store.load_jobs()[0].to_dict())))
        assert source_references(restored) == source_references(first, alternate)
        assert source_references(prepared) == source_references(restored)
        changed = replace(first, description="Nova descrição")
        prepared, status, needed = store.prepare(changed)
        assert (status, needed) == ("changed", True)
        assert source_references(prepared) == source_references(restored)


@pytest.mark.parametrize("duplicate", [False, True])
def test_regional_new_count_uses_identity_and_retains_original_sources(monkeypatch, duplicate):
    base = job("1", latitude=0, longitude=0)
    fresh = job("2", source="99jobs", latitude=0, longitude=0,
                url=base.url if duplicate else "https://example.com/jobs/2")
    monkeypatch.setattr(nearby, "_load_base_jobs", lambda: [base])
    monkeypatch.setattr(nearby, "nearby_cities", lambda *a, **kw: [{"name": "Centro"}])
    monkeypatch.setattr(nearby, "collect_gupy_nearby", lambda *a, **kw: [fresh])
    monkeypatch.setattr(nearby, "collect_99jobs_nearby", lambda *a, **kw: [])
    monkeypatch.setattr(nearby, "collect_vagas_com", lambda *a, **kw: [])
    result = nearby.search_nearby(latitude=0, longitude=0, radius_km=30, force_refresh=True)
    assert result["total"] == (1 if duplicate else 2)
    assert result["newly_collected"] == (0 if duplicate else 1)
    if duplicate:
        assert len(result["jobs"][0]["metadata"]["source_references"]) == 2
