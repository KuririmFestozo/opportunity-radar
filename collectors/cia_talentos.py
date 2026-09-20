"""Cia de Talentos public-panel defensive parser; disabled by default."""
from __future__ import annotations

import hashlib
import json

from collectors.common import get_text
from collectors.public_early_career import canonical_url, clean, normalize, soup
from models.job import Job

DEFAULT_URL = "https://ciadetalentos.com.br/"


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _parse_hydration(html: str, base_url: str) -> list[Job]:
    doc = soup(html)
    jobs = {}
    payloads = []
    for script in doc.find_all("script"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw or raw[:1] not in "[{":
            continue
        try:
            payloads.append(json.loads(raw))
        except Exception:
            continue
    for payload in payloads:
        for row in _walk(payload):
            title = clean(row.get("title") or row.get("titulo") or row.get("name") or row.get("nome") or row.get("processName"))
            href = clean(row.get("url") or row.get("link") or row.get("href"))
            if not title or not href:
                continue
            ntitle = normalize(title)
            if not any(x in ntitle for x in ("estagio", "trainee", "aprendiz", "intern")):
                continue
            url = canonical_url(base_url, href)
            raw_id = clean(row.get("id") or row.get("jobId") or row.get("processId"))
            native = raw_id or hashlib.sha1((normalize(title) + "|" + url).encode()).hexdigest()[:18]
            company = clean(row.get("company") or row.get("empresa") or row.get("companyName")) or "Cia de Talentos / empresa anunciante"
            location = clean(row.get("city") or row.get("cidade") or row.get("location") or row.get("localidade"))
            employment = "trainee" if "trainee" in ntitle else ("apprentice" if "aprendiz" in ntitle else "internship")
            job = Job(
                source="cia_talentos",
                source_job_id=f"cia_talentos:{native}",
                company=company,
                title=title,
                location=location,
                url=url,
                employment_type=employment,
                source_type="public_html",
                metadata={"platform": "cia_talentos", "coverage": "public_hydration_only"},
            )
            jobs.setdefault(job.source_job_id, job)
    return list(jobs.values())


def collect_cia_talentos(config: dict) -> list[Job]:
    url = config.get("list_url") or DEFAULT_URL
    jobs = _parse_hydration(get_text(url), url)
    jobs = jobs[: max(1, min(int(config.get("max_jobs", 500)), 3000))]
    if config.get("show_incremental_stats", True):
        print(f"[PUBLIC] Cia de Talentos: {len(jobs)} vagas públicas" if jobs else "[SKIP] Cia de Talentos: painel público dinâmico sem contrato HTML/JSON estável confirmado.")
    return jobs
