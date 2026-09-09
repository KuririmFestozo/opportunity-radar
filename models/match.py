from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class JobMatch:
    profile_id: str
    job_key: str
    score: int
    course_score: int
    distance_km: Optional[float]
    eligible: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
