import pytest

import storage.backend as backend_module


class _FakeSQLite:
    pass


class _FakePostgres:
    def __init__(self, *, supports_writes):
        self.supports_writes = supports_writes
        self.closed = False

    def close(self):
        self.closed = True


def test_backend_defaults_to_sqlite(monkeypatch):
    monkeypatch.delenv("OPPORTUNITY_BACKEND", raising=False)
    fake = _FakeSQLite()
    monkeypatch.setattr(
        backend_module,
        "SQLiteOpportunityRepository",
        lambda: fake,
    )

    repository, backend = backend_module.create_repository()

    assert backend == "sqlite"
    assert repository is fake


def test_backend_name_is_normalized(monkeypatch):
    monkeypatch.setenv("OPPORTUNITY_BACKEND", " PostgreSQL ")

    assert backend_module.selected_backend() == "postgres"


def test_invalid_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("OPPORTUNITY_BACKEND", "memory")

    with pytest.raises(ValueError, match="OPPORTUNITY_BACKEND"):
        backend_module.selected_backend()


def test_postgres_cutover_is_blocked_until_writes_are_approved(monkeypatch):
    monkeypatch.setenv("OPPORTUNITY_BACKEND", "postgres")
    fake = _FakePostgres(supports_writes=False)
    monkeypatch.setattr(
        backend_module,
        "PostgresOpportunityRepository",
        lambda: fake,
    )

    with pytest.raises(RuntimeError, match="ainda não foi liberado"):
        backend_module.create_repository()

    assert fake.closed is True


def test_postgres_is_selected_after_write_capability_is_enabled(monkeypatch):
    monkeypatch.setenv("OPPORTUNITY_BACKEND", "postgres")
    fake = _FakePostgres(supports_writes=True)
    monkeypatch.setattr(
        backend_module,
        "PostgresOpportunityRepository",
        lambda: fake,
    )

    repository, backend = backend_module.create_repository()

    assert backend == "postgres"
    assert repository is fake
    assert fake.closed is False
