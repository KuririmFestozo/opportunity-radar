"""Repository backend selection for the collection pipeline."""

from __future__ import annotations

import os
from typing import Any

from storage.postgres_repository import PostgresOpportunityRepository
from storage.sqlite_repository import SQLiteOpportunityRepository


SUPPORTED_BACKENDS = {"sqlite", "postgres"}


def selected_backend() -> str:
    """Return the configured persistence backend, defaulting safely to SQLite."""
    backend = os.getenv("OPPORTUNITY_BACKEND", "sqlite").strip().lower()
    backend = backend or "sqlite"
    if backend == "postgresql":
        backend = "postgres"
    if backend not in SUPPORTED_BACKENDS:
        choices = ", ".join(sorted(SUPPORTED_BACKENDS))
        raise ValueError(
            f"OPPORTUNITY_BACKEND inválido: {backend!r}. Use: {choices}."
        )
    return backend


def create_repository() -> tuple[Any, str]:
    """Create the configured repository without allowing an unsafe cutover."""
    backend = selected_backend()
    if backend == "sqlite":
        return SQLiteOpportunityRepository(), backend

    repository = PostgresOpportunityRepository()
    if not getattr(repository, "supports_writes", False):
        repository.close()
        raise RuntimeError(
            "Backend PostgreSQL ainda não foi liberado para escrita. "
            "Conclua o smoke test do CP5 antes de definir "
            "OPPORTUNITY_BACKEND=postgres."
        )
    return repository, backend
