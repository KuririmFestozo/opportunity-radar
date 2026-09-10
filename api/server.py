from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator

from api.nearby import existing_nearby, search_nearby
from processing.geolocation import resolve_location


OUTPUT_DIR = Path("output")
INDEX_PATH = OUTPUT_DIR / "index.html"
JOBS_PATH = OUTPUT_DIR / "jobs.json"
STATS_PATH = OUTPUT_DIR / "stats.json"

app = FastAPI(
    title="Opportunity Radar API",
    version="3.13.1",
    description="Local API for cached and on-demand opportunity searches.",
)


class NearbySearchRequest(BaseModel):
    location: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=50, ge=5, le=250)
    include_remote: bool = False
    force_refresh: bool = False
    intent: str | None = None

    @model_validator(mode="after")
    def validate_target(self):
        has_coordinates = self.latitude is not None and self.longitude is not None
        if not has_coordinates and not (self.location or "").strip():
            raise ValueError("Informe location ou latitude/longitude.")
        allowed_intents = {None, "internship", "summer_internship", "seasonal_job", "trainee", "apprentice", "entry_level"}
        if self.intent not in allowed_intents:
            raise ValueError("Tipo regional inválido.")
        return self


@app.get("/", include_in_schema=False)
def dashboard():
    if not INDEX_PATH.exists():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Dashboard ainda não foi gerado. Rode `python main.py` primeiro.",
            },
        )
    return FileResponse(INDEX_PATH)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "dashboard_ready": INDEX_PATH.exists(),
        "base_ready": JOBS_PATH.exists(),
    }


@app.get("/api/jobs")
def jobs():
    return _read_json(JOBS_PATH, [])


@app.get("/api/stats")
def stats():
    return _read_json(STATS_PATH, {})


@app.get("/api/jobs/nearby")
def jobs_nearby(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=50, ge=5, le=250),
    include_remote: bool = False,
):
    return existing_nearby(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        include_remote=include_remote,
    )


@app.post("/api/search")
def dynamic_search(request: NearbySearchRequest):
    latitude, longitude, resolved_label, country_code = _resolve_target(request)

    result = search_nearby(
        latitude=latitude,
        longitude=longitude,
        radius_km=request.radius_km,
        include_remote=request.include_remote,
        force_refresh=request.force_refresh,
        country_code=country_code,
        intent=request.intent,
    )
    result["resolved_location"] = resolved_label
    return result


def _resolve_target(request: NearbySearchRequest) -> tuple[float, float, str, str | None]:
    if request.latitude is not None and request.longitude is not None:
        return request.latitude, request.longitude, request.location or "Localização atual", None

    resolved = resolve_location((request.location or "").strip())
    if not resolved:
        raise HTTPException(
            status_code=422,
            detail="Não consegui localizar essa cidade. Tente algo como `São Carlos, SP`.",
        )

    return (
        float(resolved["latitude"]),
        float(resolved["longitude"]),
        f'{resolved["city"]} ({resolved["country_code"]})',
        resolved.get("country_code"),
    )


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
