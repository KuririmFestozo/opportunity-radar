from config.catalogs import COURSES, INTENTS


# These searches are deliberately profile-independent.
# Their purpose is to populate the universe of opportunities first.
BROAD_QUERIES_PT = [
    # Internship / general
    "estagio",
    "programa de estagio",
    "estagiario",

    # Brazilian summer / vacation programs
    "estagio de verao",
    "programa de estagio de verao",
    "estagio de ferias",
    "programa de estagio de ferias",
    "programa de ferias",
    "summer internship",

    # Seasonal / summer jobs
    "summer job",
    "trabalho de ferias",
    "trabalho temporario de verao",

    # Other intentions
    "trainee",
    "programa trainee",
    "jovem aprendiz",
    "aprendiz",
    "iniciacao cientifica",
    "estagio pesquisa",
    "junior",
]


def build_collection_queries(max_queries: int = 60) -> list[str]:
    """
    Builds a broad search universe without looking at any user's profile.

    Strategy:
    1) generic opportunity queries;
    2) internship queries for every registered course;
    3) summer/férias queries for every registered course;
    4) trainee queries for every registered course.

    This means adding a course to catalogs.py automatically expands collection.
    """
    queries = list(BROAD_QUERIES_PT)

    for _, course in COURSES.items():
        pt_terms = course.get("search_terms_pt", [])
        if not pt_terms:
            continue

        # Main course label/term.
        primary = pt_terms[0]
        queries.extend([
            f"estagio {primary}",
            f"programa de estagio {primary}",
            f"estagio de ferias {primary}",
            f"estagio de verao {primary}",
            f"trainee {primary}",
        ])

        # One adjacent specialty improves recall without exploding requests.
        if len(pt_terms) > 1:
            secondary = pt_terms[1]
            queries.extend([
                f"estagio {secondary}",
                f"estagio de ferias {secondary}",
            ])

    return _unique(queries)[:max_queries]


def _unique(values):
    seen = set()
    out = []
    for value in values:
        key = value.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
