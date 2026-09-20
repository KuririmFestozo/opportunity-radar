from collectors import successfactors_incremental as sfinc


def _tile(job_id: str, title: str = "Job"):
    return (
        f'<li class="job-tile job-id-{job_id}" '
        f'data-url="/job/{title}/{job_id}/">'
        f'<a class="jobTitle-link" href="/job/{title}/{job_id}/">{title}</a>'
        "</li>"
    )


def test_tile_probe_stops_tenant_after_two_known_pages(monkeypatch):
    pages = {
        0: _tile("101") + _tile("102"),
        2: _tile("103") + _tile("104"),
    }

    def fake_get(url):
        start = int(url.split("startrow=")[1])
        return pages.get(start, "")

    monkeypatch.setattr(sfinc, "get_text", fake_get)

    result = sfinc.probe_successfactors_recent(
        {
            "id": "ternium",
            "career_url": "https://example.com/",
            "try_tile_search": True,
        },
        {"ternium:101", "ternium:102", "ternium:103", "ternium:104"},
        consecutive_known_pages=2,
    )

    assert result.supported is True
    assert result.safe_stop is True
    assert result.pages == 2
    assert result.new_native_ids == set()


def test_tile_probe_forces_full_when_new_id_appears(monkeypatch):
    monkeypatch.setattr(
        sfinc,
        "get_text",
        lambda url: _tile("101") + _tile("999"),
    )

    result = sfinc.probe_successfactors_recent(
        {
            "id": "ternium",
            "career_url": "https://example.com/",
            "try_tile_search": True,
        },
        {"ternium:101"},
    )

    assert result.supported is True
    assert result.safe_stop is False
    assert result.new_native_ids == {"999"}


def test_probe_disabled_without_known_ids():
    result = sfinc.probe_successfactors_recent(
        {
            "id": "ternium",
            "career_url": "https://example.com/",
            "try_tile_search": True,
        },
        set(),
    )
    assert result.supported is False
    assert result.safe_stop is False
