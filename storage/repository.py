"""Persistence contract for Opportunity Radar.

The pipeline depends on this interface instead of depending directly on
SQLite/JobStore details. CP5 can provide another implementation without
changing collectors or classification logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

from models.job import Job


@runtime_checkable
class OpportunityRepository(Protocol):
    """Repository contract consumed by the collection pipeline."""

    @property
    def path(self) -> Path:
        ...

    def close(self) -> None:
        ...

    def commit(self) -> None:
        ...

    def bootstrap_from_json(self, path: str | Path) -> dict[str, Any]:
        ...

    def count_postings(self) -> int:
        ...

    def known_posting_ids(
        self,
        source: str,
        *,
        prefix: str | None = None,
    ) -> set[str]:
        ...

    def prepare_posting(self, incoming: Job) -> tuple[Job, str, bool]:
        ...

    def upsert_posting(
        self,
        job: Job,
        *,
        seen_at: str | None = None,
        processing_version: str | None = None,
        commit: bool = False,
    ) -> None:
        ...

    def touch_posting(
        self,
        source: str,
        source_job_id: str,
        *,
        seen_at: str | None = None,
        commit: bool = False,
    ) -> None:
        ...

    def load_postings(self, *, active_only: bool = True) -> list[Job]:
        """Load postings hydrated from relational opportunity classification."""
        ...

    def load_opportunities(
        self,
        *,
        active_only: bool = True,
    ) -> list[Job]:
        """Load the user-facing catalog from relational opportunities."""
        ...

    def known_discovery_ids(
        self,
        source: str,
        *,
        prefix: str | None = None,
    ) -> set[str]:
        ...

    def record_discoveries(
        self,
        source: str,
        source_job_ids: Iterable[str],
        *,
        scope_status: str = "catalog",
        seen_at: str | None = None,
    ) -> int:
        ...

    def mark_seen_ids(
        self,
        source: str,
        source_job_ids: Iterable[str],
        *,
        scope_status: str = "catalog",
        seen_at: str | None = None,
    ) -> dict[str, int]:
        ...

    def mark_seen_postings(
        self,
        jobs: Iterable[Job],
        *,
        seen_at: str | None = None,
    ) -> dict[str, int]:
        ...

    def reconcile_scope(
        self,
        source: str,
        seen_source_job_ids: Iterable[str],
        *,
        prefix: str | None = None,
        coverage: str = "partial",
        miss_threshold: int = 2,
        checked_at: str | None = None,
    ) -> dict[str, Any]:
        ...

    def needs_full_audit(
        self,
        source: str,
        scope_key: str,
        *,
        every_runs: int = 7,
    ) -> bool:
        ...

    def finish_scope_run(
        self,
        source: str,
        scope_key: str,
        *,
        coverage: str,
        finished_at: str | None = None,
    ) -> None:
        ...

    def lifecycle_stats(self) -> dict[str, int]:
        ...

    def sync_unified_schema(self) -> dict[str, Any]:
        ...

    def stats(self) -> dict[str, Any]:
        ...
