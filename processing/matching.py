from config.catalogs import NEGATIVE_SENIORITY
from models.job import Job
from models.match import JobMatch
from models.profile import SearchProfile
from processing.geolocation import distance_km, is_remote, resolve_location
from processing.text import contains_any, normalize


INTENT_COMPATIBILITY = {
    "summer_internship": {"summer_internship", "internship"},
    "co_op": {"co_op", "internship"},
    "internship": {"internship", "summer_internship", "co_op"},
    "trainee": {"trainee"},
    "entry_level": {"entry_level"},
    "research": {"research", "internship"},
    "apprentice": {"apprentice"},
    "seasonal_job": {"seasonal_job"},
}


def match_job(job: Job, profile: SearchProfile) -> JobMatch:
    key = f"{job.source}:{job.source_job_id}"

    if profile.course_ids:
        course_score = max(
            [job.course_scores.get(course_id, 0) for course_id in profile.course_ids]
            or [0]
        )
        score = int(course_score * 0.70)
        reasons = []

        if course_score >= 70:
            reasons.append("forte aderência ao curso")
        elif course_score >= 40:
            reasons.append("aderência parcial ao curso")
    else:
        # Intent-only profile: useful for Apprentice, Trainee, generic Summer etc.
        course_score = 100
        score = 55
        reasons = ["sem filtro de curso"]

    wanted = set(profile.intent_ids)
    detected = set(job.detected_intents)

    intent_match = False
    for desired in wanted:
        accepted = INTENT_COMPATIBILITY.get(desired, {desired})
        if detected & accepted:
            intent_match = True
            break

    if intent_match:
        score += 25
        reasons.append("tipo de oportunidade desejado")
    elif wanted:
        score -= 20
        reasons.append("tipo de oportunidade não confirmado")

    whole = " ".join([
        job.title or "",
        job.description or "",
        job.company or "",
    ])

    include_matches = contains_any(whole, profile.include_keywords)
    if include_matches:
        score += min(15, 5 * len(set(include_matches)))
        reasons.append("palavras-chave de interesse")

    exclude_matches = contains_any(whole, profile.exclude_keywords)
    if exclude_matches:
        score -= min(60, 30 * len(set(exclude_matches)))
        reasons.append("contém palavra-chave excluída")

    title_norm = normalize(job.title)
    if contains_any(title_norm, NEGATIVE_SENIORITY):
        score -= 50
        reasons.append("senioridade incompatível")

    workplace = _workplace(job)
    if profile.preferred_workplace_types:
        if workplace in profile.preferred_workplace_types:
            score += 5
            reasons.append("modalidade desejada")
        elif workplace != "unknown":
            score -= 12
            reasons.append("modalidade fora da preferência")

    # Country is an actual filter when location country is known.
    country = (job.metadata or {}).get("resolved_country")
    if profile.preferred_countries and country:
        if country not in profile.preferred_countries:
            return JobMatch(
                profile_id=profile.id,
                job_key=key,
                score=max(0, min(100, score)),
                course_score=course_score,
                distance_km=None,
                eligible=False,
                reasons=_dedupe(reasons + ["país fora da preferência"]),
            )
        else:
            score += 4
            reasons.append("país desejado")

    dist = _distance_for_profile(job, profile)
    eligible = True

    if profile.max_distance_km is not None:
        if is_remote(job) and profile.remote_ignores_distance:
            reasons.append("remoto: distância ignorada")
        elif dist is None:
            if not profile.allow_unknown_distance:
                eligible = False
                reasons.append("distância desconhecida")
        elif dist > profile.max_distance_km:
            eligible = False
            reasons.append("fora do raio escolhido")
        else:
            score += _distance_bonus(dist, profile.max_distance_km)
            reasons.append(f"dentro do raio ({dist:.0f} km)")

    score = max(0, min(100, score))

    if profile.course_ids and course_score < 25:
        eligible = False
    if not intent_match and wanted:
        eligible = False
    if score < profile.minimum_score:
        eligible = False

    return JobMatch(
        profile_id=profile.id,
        job_key=key,
        score=score,
        course_score=course_score,
        distance_km=round(dist, 1) if dist is not None else None,
        eligible=eligible,
        reasons=_dedupe(reasons),
    )


def _distance_for_profile(job, profile):
    if is_remote(job) and profile.remote_ignores_distance:
        return 0.0

    if job.latitude is None or job.longitude is None:
        return None

    lat = profile.home_latitude
    lon = profile.home_longitude

    if (lat is None or lon is None) and profile.home_city:
        resolved = resolve_location(profile.home_city)
        if resolved:
            lat = resolved["latitude"]
            lon = resolved["longitude"]

    if lat is None or lon is None:
        return None

    return distance_km(lat, lon, job.latitude, job.longitude)


def _distance_bonus(distance, radius):
    if radius <= 0:
        return 0
    fraction = max(0.0, 1.0 - distance / radius)
    return round(10 * fraction)


def _workplace(job):
    text = normalize(" ".join([
        job.workplace_type or "",
        job.location or "",
        job.description[:600] if job.description else "",
    ]))

    if any(x in text for x in ["remote", "remoto", "remota", "home office"]):
        return "remote"
    if any(x in text for x in ["hybrid", "hibrido", "hibrida"]):
        return "hybrid"
    if any(x in text for x in ["on-site", "onsite", "presencial"]):
        return "onsite"
    return "unknown"


def _dedupe(values):
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
