from models.job import Job
from collectors.common import get_json


def collect_lever(company_name: str, site: str) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{site}"
    data = get_json(url, params={"mode": "json"})

    jobs: list[Job] = []

    for item in data:
        categories = item.get("categories") or {}

        description = (
            item.get("descriptionPlain")
            or item.get("description")
            or ""
        )

        job = Job(
            source="lever",
            source_job_id=str(item.get("id", "")),
            company=company_name,
            title=item.get("text", ""),
            location=categories.get("location", "") or "",
            url=item.get("hostedUrl") or item.get("applyUrl") or "",
            description=description,
            published_at=_timestamp_to_iso(item.get("createdAt")),
            employment_type=categories.get("commitment"),
            workplace_type=item.get("workplaceType"),
        )
        jobs.append(job)

    return jobs


def _timestamp_to_iso(value):
    if not value:
        return None

    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None
