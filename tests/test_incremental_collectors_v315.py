from processing.incremental import KnownPageStopper


def test_known_page_stopper_disabled_without_known_ids():
    s = KnownPageStopper([], 2)
    assert s.observe({"1"}) is False


def test_known_page_stopper_requires_consecutive_pages():
    s = KnownPageStopper({"1", "2", "3", "4"}, 2)
    assert s.observe({"1", "2"}) is False
    assert s.observe({"3", "4"}) is True


def test_new_id_resets_streak():
    s = KnownPageStopper({"1", "2", "3"}, 2)
    assert s.observe({"1"}) is False
    assert s.observe({"1", "999"}) is False
    assert s.observe({"2"}) is False
    assert s.observe({"3"}) is True


def test_empty_page_does_not_trigger_stop():
    s = KnownPageStopper({"1"}, 1)
    assert s.observe(set()) is False
