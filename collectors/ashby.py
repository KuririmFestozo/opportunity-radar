from models.job import Job
from collectors.common import get_json


def collect_ashby(company_name: str, board_name: str) -> list[Job]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}"
    data = get_json(url, params={"includeCompensation": "true"})

    jobs: list[Job] = []

    for index, item in enumerate(data.get("jobs", [])):
        if item.get("isListed") is False:
            continue

        job_url = item.get("jobUrl") or item.get("applyUrl") or ""

        job = Job(
            source="ashby",
            source_job_id=job_url or f"{board_name}-{index}",
            company=company_name,
            title=item.get("title", ""),
            location=item.get("location", "") or "",
            url=item.get("applyUrl") or job_url,
            description=item.get("descriptionPlain") or "",
            published_at=item.get("publishedAt"),
            employment_type=item.get("employmentType"),
            workplace_type=item.get("workplaceType"),
        )
        jobs.append(job)

    return jobs
