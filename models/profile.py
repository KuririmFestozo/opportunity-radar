from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class SearchProfile:
    id: str
    name: str
    course_ids: list[str]
    intent_ids: list[str]
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    preferred_workplace_types: list[str] = field(default_factory=list)
    preferred_countries: list[str] = field(default_factory=list)
    home_city: Optional[str] = None
    home_latitude: Optional[float] = None
    home_longitude: Optional[float] = None
    max_distance_km: Optional[float] = None
    allow_unknown_distance: bool = True
    remote_ignores_distance: bool = True
    minimum_score: int = 45

    def to_dict(self) -> dict:
        return asdict(self)
