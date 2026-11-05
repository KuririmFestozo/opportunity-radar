"""Guard rails against silently dropping Gupy vacancies on API changes."""
import pytest
from collectors.gupy_global import API_URL, _extract_items, _get_payload_with_type_fallback


def test_global_url_uses_candidate_portal_route():
    assert API_URL == "https://portal.gupy.io/api/job-search/jobs"


def test_extract_items_accepts_known_collection_shapes():
    job = {"id": 1, "name": "Estágio"}
    assert _extract_items({"data": [job]}) == [job]
    assert _extract_items({"jobs": [job]}) == [job]
    assert _extract_items({"results": [job]}) == [job]
    assert _extract_items({"data": []}) == []


def test_schema_drift_never_becomes_successful_empty_collection():
    with pytest.raises(ValueError, match="formato de lista desconhecido"):
        _extract_items({"pagination": {"total": 0}})
    with pytest.raises(ValueError, match="nao e objeto"):
        _extract_items([])


def test_404_does_not_retry_an_unavailable_endpoint(monkeypatch):
    import requests
    calls = []
    response = requests.Response()
    response.status_code = 404
    error = requests.HTTPError("404: endpoint indisponivel", response=response)

    def fail(url, params, headers):
        calls.append((url, params))
        raise error

    monkeypatch.setattr("collectors.gupy_global.get_json", fail)
    with pytest.raises(requests.HTTPError):
        _get_payload_with_type_fallback({"type": "vacancy_type_summer"}, "vacancy_type_summer")
    assert len(calls) == 1


def test_portal_never_requests_offset_beyond_10000(monkeypatch, capsys):
    from collectors.gupy_global import _collect_segment
    requests = []

    def fake_json(url, params, headers):
        requests.append(params["offset"])
        return {"data": [{}] * 100}

    monkeypatch.setattr("collectors.gupy_global.get_json", fake_json)
    monkeypatch.setattr("collectors.gupy_global.job_from_item", lambda item: None)
    monkeypatch.setattr("collectors.gupy_global.time.sleep", lambda seconds: None)

    assert _collect_segment(page_size=100, max_pages=500) == []
    assert len(requests) == 100
    assert max(requests) == 9900
    assert "cobertura pode ser parcial" in capsys.readouterr().out
