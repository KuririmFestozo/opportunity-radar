import os

from collectors.common import get_json
from models.job import Job


def collect_gupy_api() -> list[Job]:
    """
    Integração opcional com a API oficial da Gupy.

    Importante:
    O token da Gupy normalmente está associado ao ambiente/empresa a que
    o usuário possui acesso. Portanto, este conector não representa uma
    busca global em todas as vagas da Gupy.
    """
    token = os.getenv("GUPY_TOKEN", "").strip()
    if not token:
        return []

    jobs: list[Job] = []
    page = 1

    while page <= 20:
        data = get_json(
            "https://api.gupy.io/api/v1/jobs",
            params={
                "status": "published",
                "publicationType": "external",
                "fields": "all",
                "perPage": 100,
                "page": page,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        items = data.get("results", []) if isinstance(data, dict) else []
        if not items:
            break

        for item in items:
            job_id = str(item.get("id", ""))
            company = (
                item.get("companyName")
                or item.get("careerPageName")
                or "Gupy"
            )
            address = item.get("address") or {}
            location = " - ".join(
                x for x in [
                    address.get("city"),
                    address.get("state"),
                ] if x
            )

            url = (
                item.get("jobUrl")
                or item.get("publicUrl")
                or item.get("url")
                or ""
            )

            jobs.append(
                Job(
                    source="gupy_api",
                    source_type="official_api",
                    source_job_id=job_id,
                    company=company,
                    title=item.get("name", ""),
                    location=location,
                    url=url,
                    description=_description(item),
                    published_at=item.get("publishedAt") or item.get("createdAt"),
                    employment_type=item.get("type"),
                    workplace_type=item.get("workplaceType"),
                    metadata={"publication_type": item.get("publicationType")},
                )
            )

        total_pages = data.get("totalPages") if isinstance(data, dict) else None
        if total_pages and page >= total_pages:
            break
        if len(items) < 100:
            break
        page += 1

    return jobs


def _description(item: dict) -> str:
    keys = [
        "description",
        "responsibilities",
        "prerequisites",
        "requirements",
        "additionalInformation",
    ]
    parts = [str(item.get(key) or "") for key in keys]
    return " ".join(part for part in parts if part).strip()
