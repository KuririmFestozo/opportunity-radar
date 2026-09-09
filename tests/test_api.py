from fastapi.testclient import TestClient

from api import server


client = TestClient(server.app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_live_search_requires_location_or_coordinates():
    response = client.post("/api/search", json={"radius_km": 50})
    assert response.status_code == 422


def test_live_search_resolves_city_and_calls_service(monkeypatch):
    monkeypatch.setattr(
        server,
        "resolve_location",
        lambda value: {
            "city": "São Carlos",
            "country_code": "BR",
            "latitude": -22.01,
            "longitude": -47.89,
        },
    )
    monkeypatch.setattr(
        server,
        "search_nearby",
        lambda **kwargs: {
            "center": {
                "latitude": kwargs["latitude"],
                "longitude": kwargs["longitude"],
                "country_code": kwargs["country_code"],
            },
            "radius_km": kwargs["radius_km"],
            "jobs": [],
            "total": 0,
        },
    )

    response = client.post(
        "/api/search",
        json={"location": "São Carlos, SP", "radius_km": 75},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["center"]["country_code"] == "BR"
    assert data["radius_km"] == 75
    assert "São Carlos" in data["resolved_location"]
