from config.successfactors import SUCCESSFACTORS_PORTALS


def test_all_successfactors_portals_enabled():
    assert SUCCESSFACTORS_PORTALS
    assert all(p.get("enabled") is True for p in SUCCESSFACTORS_PORTALS)


def test_expanded_successfactors_sources_present():
    ids = {p["id"] for p in SUCCESSFACTORS_PORTALS}
    assert {
        "zf",
        "schaeffler",
        "scania",
        "andritz",
        "ey",
        "volvo_group",
    } <= ids


def test_successfactors_ids_unique():
    ids = [p["id"] for p in SUCCESSFACTORS_PORTALS]
    assert len(ids) == len(set(ids))


def test_bootstrap_caps_present():
    for portal in SUCCESSFACTORS_PORTALS:
        assert int(portal.get("bootstrap_max_pages", 0)) >= 1
        assert int(portal.get("bootstrap_max_details", -1)) >= 0
