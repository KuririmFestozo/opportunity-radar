from dataclasses import replace

import pytest

from models.job import Job
from models.profile import SearchProfile
from processing.classification import classify_job
from processing.geolocation import enrich_job_location
from processing.matching import match_job
from storage.job_store import JobStore


def job(**overrides):
    values = dict(
        source="test", source_job_id="1", company="Empresa",
        title="Programa", location="São Carlos - SP",
        url="https://example.com/1", description="",
    )
    values.update(overrides)
    return Job(**values)


def profile(**overrides):
    values = dict(
        id="test", name="Teste", course_ids=[], intent_ids=[], minimum_score=0,
    )
    values.update(overrides)
    return SearchProfile(**values)


def test_changed_location_is_geocoded_again_and_then_reused(tmp_path, monkeypatch):
    cached = job(latitude=-22.01, longitude=-47.89, location_confidence="city",
                 metadata={"resolved_city": "São Carlos", "resolved_country": "BR",
                           "search_distance_km": 5})
    calls = []

    def resolve(value):
        calls.append(value)
        return dict(latitude=-3.1, longitude=-60.0, city="Manaus",
                    country_code="BR", confidence="city+country")

    monkeypatch.setattr("processing.geolocation.resolve_location", resolve)
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(cached, commit=True)
        prepared, status, needed = store.prepare(job(location="Manaus - AM"))
        assert (status, needed) == ("changed", True)
        assert prepared.latitude is None and prepared.longitude is None
        assert prepared.location_confidence is None
        assert not {"resolved_city", "resolved_country", "search_distance_km"} & prepared.metadata.keys()
        enrich_job_location(prepared)
        assert calls == ["Manaus - AM"]
        assert (prepared.latitude, prepared.longitude) == (-3.1, -60.0)
        store.upsert(prepared, commit=True)
        reused, status, needed = store.prepare(job(location="Manaus - AM"))
        assert (status, needed) == ("unchanged", False)
        assert (reused.latitude, reused.longitude) == (-3.1, -60.0)


@pytest.mark.parametrize("updates", [{"title": "Novo título"}, {"description": "Nova descrição"}, {"location": ""}])
def test_unrelated_changes_and_sparse_locations_preserve_coordinates(tmp_path, updates):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job(latitude=-22.01, longitude=-47.89, location_confidence="city"), commit=True)
        prepared, _, _ = store.prepare(job(**updates))
        assert (prepared.latitude, prepared.longitude) == (-22.01, -47.89)
        assert prepared.location_confidence == "city"
        assert prepared.location == "São Carlos - SP"


def test_changed_location_does_not_keep_country_when_resolution_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("processing.geolocation.resolve_location", lambda _: None)
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job(latitude=1, longitude=2, metadata={
            "resolved_country": "BR", "resolved_city": "São Carlos",
            "gupy_city": "São Carlos", "gupy_country": "Brasil",
        }), commit=True)
        prepared, _, _ = store.prepare(job(location="Local não identificado"))
        enrich_job_location(prepared)
        assert prepared.latitude is None and prepared.longitude is None
        assert "resolved_country" not in prepared.metadata
        assert "gupy_city" not in prepared.metadata


def test_changed_location_preserves_fresh_coordinate_pair(tmp_path):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job(latitude=1, longitude=2), commit=True)
        prepared, _, _ = store.prepare(job(location="Manaus - AM", latitude=-3.1, longitude=-60))
        assert (prepared.latitude, prepared.longitude) == (-3.1, -60)


def test_changed_location_preserves_country_supplied_by_source(tmp_path):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job(metadata={"resolved_country": "BR"}), commit=True)
        prepared, _, _ = store.prepare(job(location="Canada", metadata={
            "gupy_country": "Canada", "resolved_country": "CA",
        }))
        enrich_job_location(prepared)
        assert prepared.metadata["resolved_country"] == "CA"


def test_changed_location_never_mixes_new_and_cached_coordinates(tmp_path):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job(latitude=1, longitude=2), commit=True)
        prepared, _, _ = store.prepare(job(location="Manaus - AM", latitude=-3.1))
        assert prepared.latitude is None and prepared.longitude is None


def test_remote_change_invalidates_cached_geocoding(tmp_path):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job(latitude=1, longitude=2, workplace_type="onsite"), commit=True)
        prepared, status, needed = store.prepare(job(workplace_type="remote"))
        assert (status, needed) == ("changed", True)
        assert prepared.latitude is None and prepared.longitude is None


@pytest.mark.parametrize("key,before,after,intent", [
    ("source_level", "Estágio", "Trainee", "trainee"),
    ("gupy_job_type", "vacancy_type_internship", "vacancy_type_apprentice", "apprentice"),
])
def test_semantic_metadata_changes_reclassify_job(tmp_path, key, before, after, intent):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(classify_job(job(metadata={key: before})), commit=True)
        prepared, status, needed = store.prepare(job(metadata={key: after}))
        assert (status, needed) == ("changed", True)
        classify_job(prepared)
        assert prepared.detected_intents == [intent]
        store.upsert(prepared, commit=True)
        assert store.prepare(job(metadata={key: after}))[1:] == ("unchanged", False)


@pytest.mark.parametrize("key", ["gupy_city", "gupy_state", "gupy_country"])
def test_source_location_metadata_invalidates_processing(tmp_path, key):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job(metadata={key: "Anterior"}, latitude=1, longitude=2), commit=True)
        prepared, status, needed = store.prepare(job(metadata={key: "Novo"}))
        assert (status, needed) == ("changed", True)
        assert prepared.latitude is None and prepared.longitude is None


@pytest.mark.parametrize("key", ["discovered_from", "detail_fetched", "course_score_reasons", "search_distance_km", "resolved_city"])
def test_diagnostic_and_derived_metadata_do_not_reprocess(tmp_path, key):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(job(metadata={key: "anterior", "source_level": "Estágio"}), commit=True)
        assert store.prepare(job(metadata={key: "novo"}))[1:] == ("unchanged", False)


def test_explicit_empty_semantic_metadata_removes_previous_signal(tmp_path):
    with JobStore(tmp_path / "jobs.db") as store:
        store.upsert(classify_job(job(metadata={"source_level": "Estágio"})), commit=True)
        prepared, status, needed = store.prepare(job(metadata={"source_level": ""}))
        assert (status, needed) == ("changed", True)
        assert classify_job(prepared).detected_intents == []


@pytest.mark.parametrize("field", ["title", "description", "company"])
def test_excluded_terms_make_profile_ineligible_without_changing_job(field):
    candidate = job(**{field: "Vendas"}, course_scores={"computer_science": 100})
    before = candidate.to_dict()
    matching = match_job(candidate, profile(course_ids=["computer_science"], exclude_keywords=["vendas"]))
    assert matching.eligible is False
    assert "contém palavra-chave excluída" in matching.reasons
    assert candidate.to_dict() == before
    assert match_job(candidate, profile()).eligible is True


def test_excluded_terms_use_existing_normalization_and_word_boundaries():
    preset = profile(exclude_keywords=["vendas", "sênior"])
    assert not match_job(job(description="SENIOR"), preset).eligible
    assert match_job(job(description="Revendas internacionais"), preset).eligible


def test_multi_course_profile_uses_best_affinity_independent_of_order():
    candidate = job(course_scores={"computer_science": 0, "data_science": 90})
    preset = profile(course_ids=["computer_science", "data_science"], minimum_score=45)
    result = match_job(candidate, preset)
    assert result.eligible and result.course_score == 90
    assert result.score == match_job(candidate, replace(preset, course_ids=["data_science"])).score
    assert match_job(candidate, replace(preset, course_ids=list(reversed(preset.course_ids)))) == result
