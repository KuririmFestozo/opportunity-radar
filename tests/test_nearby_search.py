from models.job import Job
from api import nearby as nearby_api
from processing import geolocation


def test_nearby_cities_sorts_and_applies_radius(monkeypatch):
    monkeypatch.setattr(
        geolocation,
        "_city_records",
        lambda: (
            ("Centro", "BR", 0.0, 0.0, 1000),
            ("Perto", "BR", 0.1, 0.0, 500),
            ("Longe", "BR", 3.0, 0.0, 999999),
        ),
    )
    cities = geolocation.nearby_cities(0.0, 0.0, 30, max_cities=10)
    assert [city["name"] for city in cities] == ["Centro", "Perto"]
    assert cities[0]["distance_km"] == 0.0


def test_filter_by_radius_marks_search_distance():
    local = Job(
        source="test",
        source_job_id="1",
        company="Empresa",
        title="Estágio",
        location="Cidade",
        url="https://example.com/1",
        latitude=0.0,
        longitude=0.1,
    )
    far = Job(
        source="test",
        source_job_id="2",
        company="Empresa 2",
        title="Estágio",
        location="Outra",
        url="https://example.com/2",
        latitude=0.0,
        longitude=2.0,
    )

    result = nearby_api._filter_by_radius(
        [local, far],
        latitude=0.0,
        longitude=0.0,
        radius_km=30,
        include_remote=False,
    )
    assert result == [local]
    assert 10 < local.metadata["search_distance_km"] < 12


def test_live_search_combines_base_and_new_jobs(monkeypatch):
    base = Job(
        source="test",
        source_job_id="base",
        company="Base",
        title="Estágio Engenharia Elétrica",
        location="Centro",
        url="https://example.com/base",
        latitude=0.0,
        longitude=0.05,
    )
    fresh = Job(
        source="gupy_global",
        source_job_id="fresh",
        company="Nova",
        title="Estágio Engenharia Elétrica",
        location="Centro",
        url="https://example.com/fresh",
        latitude=0.0,
        longitude=0.08,
        employment_type="vacancy_type_internship",
        metadata={"gupy_job_type": "vacancy_type_internship"},
    )

    monkeypatch.setattr(nearby_api, "_load_base_jobs", lambda: [base])
    monkeypatch.setattr(
        nearby_api,
        "nearby_cities",
        lambda *args, **kwargs: [
            {
                "name": "Centro",
                "country_code": "BR",
                "latitude": 0.0,
                "longitude": 0.0,
                "distance_km": 0.0,
                "population": 1000,
            }
        ],
    )
    monkeypatch.setattr(nearby_api, "collect_gupy_nearby", lambda *args, **kwargs: [fresh])
    monkeypatch.setattr(nearby_api, "collect_99jobs_nearby", lambda *args, **kwargs: [])
    monkeypatch.setattr(nearby_api, "collect_vagas_com", lambda *args, **kwargs: [])

    result = nearby_api.search_nearby(
        latitude=0.0,
        longitude=0.0,
        radius_km=30,
        force_refresh=True,
    )

    assert result["cached_jobs"] == 1
    assert result["newly_collected"] == 1
    assert result["total"] == 2
    dynamic = next(job for job in result["jobs"] if job["source_job_id"] == "fresh")
    assert dynamic["metadata"]["dynamic_search"] is True
    assert "internship" in dynamic["detected_intents"]
