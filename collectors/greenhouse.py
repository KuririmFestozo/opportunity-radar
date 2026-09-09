import html
import re

from models.job import Job
from collectors.common import get_json


def collect_greenhouse(company_name: str, board_token: str) -> list[Job]:
    url = (
        "https://boards-api.greenhouse.io/v1/boards/"
        f"{board_token}/jobs"
    )
    data = get_json(url, params={"content": "true"})

    jobs: list[Job] = []

    for item in data.get("jobs", []):
        raw_content = item.get("content") or ""

        job = Job(
            source="greenhouse",
            source_job_id=str(item.get("id", "")),
            company=company_name,
            title=item.get("title", ""),
            location=(item.get("location") or {}).get("name", "") or "",
            url=item.get("absolute_url") or "",
            description=_strip_html(raw_content),
            published_at=item.get("updated_at"),
            employment_type=None,
            workplace_type=None,
        )
        jobs.append(job)

    return jobs


def _strip_html(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()
