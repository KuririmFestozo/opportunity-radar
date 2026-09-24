"""Exact source identity for storage; conservative URL evidence for the catalog."""

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from dataclasses import replace
from typing import Iterable
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from models.job import Job


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", (value or "").lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#]+", " ", value)).strip()


def source_identity(job: Job) -> tuple[str, str] | None:
    """Match the SQLite primary key without interpreting source-specific IDs."""
    if job.source and job.source_job_id:
        return job.source, job.source_job_id
    return None


def source_references(*jobs: Job) -> list[dict]:
    """Keep original URLs, including tracking, for every observed source/ID."""
    refs = set()
    for job in jobs:
        existing = (job.metadata or {}).get("source_references", [])
        candidates = existing if isinstance(existing, list) else []
        for ref in [*candidates, dict(source=job.source, source_job_id=job.source_job_id, url=job.url)]:
            if isinstance(ref, dict) and all(isinstance(ref.get(k), str) for k in ("source", "source_job_id", "url")):
                refs.add((ref["source"], ref["source_job_id"], ref["url"]))
    return [dict(source=source, source_job_id=identifier, url=url) for source, identifier, url in sorted(refs)]


def source_identities(job: Job) -> set[tuple[str, str]]:
    return {(r["source"], r["source_job_id"]) for r in source_references(job)
            if r["source"] and r["source_job_id"]}


def fingerprint(job: Job) -> str:
    """Stable exact identity, never a company/title/location similarity key."""
    identity = source_identity(job)
    payload = identity if identity else (job.source, job.url, job.title, job.location)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def canonical_job_url(url: str) -> str:
    """Remove only known tracking; preserve paths, fragments and identity queries."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return ""
        tracking = {"fbclid", "gclid", "mc_cid", "mc_eid"}
        query = []
        for item in parts.query.split("&") if parts.query else []:
            key = unquote_plus(item.split("=", 1)[0]).lower()
            if not key.startswith("utm_") and key not in tracking:
                query.append(item)
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "&".join(query), parts.fragment))
    except ValueError:
        return ""


def _detail_url(job: Job) -> str:
    url = canonical_job_url(job.url)
    if not url:
        return ""
    parts = urlsplit(url)
    # Generic home/search/application URLs are not evidence of identity.
    segments = parts.path.strip("/").split("/")
    has_id = any(
        re.fullmatch(r"v?\d+(?:[-_].+)?|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", segment)
        for index, segment in enumerate(segments)
        if index == len(segments) - 1 or (index > 0 and segments[index - 1] in {"job", "jobs", "vagas"})
    )
    query_id = any(
        unquote_plus(item.split("=", 1)[0]).lower() in {"jobid", "job_id", "requisitionid", "gh_jid", "reqid"}
        and "=" in item and item.split("=", 1)[1]
        for item in parts.query.split("&")
    )
    return url if has_id or query_id else ""


def _compatible(a: Job, b: Job) -> bool:
    # Shared URLs cannot override conflicting native IDs, even after a merge.
    for source, identifier in source_identities(a):
        if any(src == source and other != identifier for src, other in source_identities(b)):
            return False
    generic = {"gupy", "99jobs", "vagas com", "empresa nao identificada", "ciee empresa nao identificada"}
    company = _norm(a.company)
    if not company or company in generic or company != _norm(b.company):
        return False
    if not _norm(a.title) or _norm(a.title) != _norm(b.title):
        return False
    if a.published_at and b.published_at and a.published_at != b.published_at:
        return False
    for attr in ("location", "workplace_type", "employment_type", "description"):
        left, right = getattr(a, attr), getattr(b, attr)
        if left and right and _norm(left) != _norm(right):
            return False
    for key in ("department", "unit", "team", "business_unit", "portal_id", "native_job_id",
                "gupy_city", "gupy_state", "gupy_country"):
        left, right = (a.metadata or {}).get(key), (b.metadata or {}).get(key)
        if (left or right) and _norm(str(left or "")) != _norm(str(right or "")):
            return False
    return True


def _merge(jobs: list[Job]) -> Job:
    winner = max(jobs, key=lambda j: len(j.description or "") + len(j.location or "") + (100 if j.published_at else 0))
    if len(jobs) == 1:
        return winner
    metadata = deepcopy(winner.metadata or {})
    metadata["source_references"] = source_references(*jobs)
    values = {}
    if any(job.source != winner.source for job in jobs):
        # Compatible cross-source records may fill gaps, but must not lose the
        # evidence that prevents a later merge with a conflicting publication.
        for attr in ("location", "published_at", "workplace_type", "employment_type", "description"):
            if not getattr(winner, attr):
                values[attr] = next((getattr(job, attr) for job in jobs if getattr(job, attr)), getattr(winner, attr))
    return replace(winner, metadata=metadata, **values)


def deduplicate_source_jobs(jobs: Iterable[Job]) -> list[Job]:
    """Storage stage: collapse only repeated nonempty source/ID pairs."""
    groups: dict[tuple, list[Job]] = {}
    for index, job in enumerate(jobs):
        key = source_identity(job) or (None, index)
        groups.setdefault(key, []).append(job)
    return [_merge(group) for group in groups.values()]


def deduplicate_job_groups(jobs: list[Job]) -> list[list[Job]]:
    """Return conservative catalog groups before merging their fields.

    CP4 persists these exact groups so database identity and exported catalog
    identity cannot drift apart.
    """
    groups: list[list[Job]] = []
    by_url: dict[str, list[int]] = {}
    for job in deduplicate_source_jobs(jobs):
        url = _detail_url(job)
        for index in by_url.get(url, []):
            if all(_compatible(member, job) for member in groups[index]):
                groups[index].append(job)
                break
        else:
            if url:
                by_url.setdefault(url, []).append(len(groups))
            groups.append([job])
    return groups


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    """Catalog stage: exact identity, then matching detail URLs with no conflicts.

    Compare every member so sparse records cannot bridge conflicting dates or
    departments. Uncertain records remain separate. Inputs are not mutated.
    """
    return [_merge(group) for group in deduplicate_job_groups(jobs)]
