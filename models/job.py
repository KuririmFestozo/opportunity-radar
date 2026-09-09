from dataclasses import dataclass, asdict, field
from typing import Optional, Any


@dataclass
class Job:
    source: str
    source_job_id: str
    company: str
    title: str
    location: str
    url: str
    description: str = ""
    published_at: Optional[str] = None
    employment_type: Optional[str] = None
    workplace_type: Optional[str] = None
    source_type: str = "official_api"
    salary: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_confidence: Optional[str] = None
    detected_intents: list[str] = field(default_factory=list)
    course_scores: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
