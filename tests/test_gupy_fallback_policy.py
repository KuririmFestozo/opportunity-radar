"""Exercise bounded Gupy fallback policy without accessing live portals."""
from main import _should_run_gupy_fallback


def test_fallback_enabled_if_global_request_fails_or_returns_empty():
    cfg = {"enabled": False, "on_global_failure": True}
    assert _should_run_gupy_fallback(global_enabled=True, global_jobs=None, fallback_cfg=cfg)
    assert _should_run_gupy_fallback(global_enabled=True, global_jobs=[], fallback_cfg=cfg)


def test_fallback_not_used_when_global_collector_has_results():
    cfg = {"enabled": False, "on_global_failure": True}
    assert not _should_run_gupy_fallback(global_enabled=True, global_jobs=[object()], fallback_cfg=cfg)


def test_fallback_opt_in_and_emergency_disable():
    assert _should_run_gupy_fallback(global_enabled=False, global_jobs=None,
                                     fallback_cfg={"enabled": True})
    assert not _should_run_gupy_fallback(global_enabled=False, global_jobs=None,
                                         fallback_cfg={"enabled": False})
    assert not _should_run_gupy_fallback(global_enabled=True, global_jobs=None,
                                         fallback_cfg={"enabled": False, "on_global_failure": False})
