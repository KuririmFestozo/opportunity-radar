from config.catalogs import COURSES, INTENTS
from models.profile import SearchProfile


def build_public_queries(profile: SearchProfile) -> list[str]:
    """
    Balanced Portuguese queries for Brazilian public sources.

    We deliberately interleave intent prefixes instead of generating every
    internship query first. This guarantees coverage for Trainee, Research,
    Apprentice, etc. without creating dozens of requests.
    """
    course_terms = []
    for course_id in profile.course_ids:
        course = COURSES.get(course_id)
        if course:
            course_terms.extend(course.get("search_terms_pt", [])[:3])

    prefixes = []
    for intent_id in profile.intent_ids:
        intent = INTENTS.get(intent_id)
        if intent:
            prefixes.extend(intent.get("search_prefixes_pt", []))

    queries = []

    # Round-robin by prefix/intention: each opportunity type gets coverage.
    for prefix in _unique(prefixes):
        for term in _unique(course_terms):
            queries.append(f"{prefix} {term}".strip())

    return _unique(queries)[:30]


def build_international_queries(profile: SearchProfile) -> list[str]:
    course_terms = []
    for course_id in profile.course_ids:
        course = COURSES.get(course_id)
        if course:
            course_terms.extend(course.get("search_terms_en", [])[:3])

    suffixes = []
    for intent_id in profile.intent_ids:
        intent = INTENTS.get(intent_id)
        if intent:
            suffixes.extend(intent.get("search_suffixes_en", []))

    queries = []

    # Interleave by intent suffix as well so Summer / Co-op / New Grad do not
    # disappear behind generic internship queries.
    for suffix in _unique(suffixes):
        for term in _unique(course_terms):
            queries.append(f"{term} {suffix}".strip())

    return _unique(queries)[:36]


def build_linkedin_queries(profile: SearchProfile) -> list[tuple[str, str]]:
    out = []

    for q in build_public_queries(profile)[:12]:
        out.append((q, "Brasil"))

    for q in build_international_queries(profile)[:18]:
        out.append((q, "United States"))

    return out


def _unique(values):
    seen = set()
    out = []
    for value in values:
        key = value.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
