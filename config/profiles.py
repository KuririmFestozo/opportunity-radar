from models.profile import SearchProfile


PROFILES = {
    "electrical_internship_br": SearchProfile(
        id="electrical_internship_br",
        name="Engenharia Elétrica — Estágio no Brasil",
        course_ids=["electrical_engineering"],
        intent_ids=["internship"],
        preferred_workplace_types=["remote", "hybrid", "onsite"],
        preferred_countries=["BR"],
        home_city="São Carlos - SP",
        max_distance_km=None,
        allow_unknown_distance=True,
        minimum_score=45,
    ),

    "electrical_summer_us": SearchProfile(
        id="electrical_summer_us",
        name="Engenharia Elétrica — Summer Internship / Co-op (EUA)",
        course_ids=["electrical_engineering"],
        intent_ids=["summer_internship", "co_op", "internship"],
        preferred_workplace_types=["remote", "hybrid", "onsite"],
        preferred_countries=["US"],
        max_distance_km=None,
        allow_unknown_distance=True,
        minimum_score=45,
    ),

    "electrical_all_global": SearchProfile(
        id="electrical_all_global",
        name="Engenharia Elétrica — Todas as oportunidades",
        course_ids=["electrical_engineering"],
        intent_ids=[
            "internship",
            "summer_internship",
            "seasonal_job",
            "co_op",
            "trainee",
            "entry_level",
            "research",
            "apprentice",
        ],
        preferred_workplace_types=["remote", "hybrid", "onsite"],
        preferred_countries=[],
        max_distance_km=None,
        allow_unknown_distance=True,
        minimum_score=40,
    ),

    "computer_science_internship_br": SearchProfile(
        id="computer_science_internship_br",
        name="Computação — Estágio no Brasil",
        course_ids=["computer_science", "data_science"],
        intent_ids=["internship"],
        preferred_workplace_types=["remote", "hybrid", "onsite"],
        preferred_countries=["BR"],
        home_city="São Carlos - SP",
        max_distance_km=None,
        allow_unknown_distance=True,
        minimum_score=45,
    ),

    "computer_science_all_global": SearchProfile(
        id="computer_science_all_global",
        name="Computação — Todas as oportunidades",
        course_ids=["computer_science", "data_science"],
        intent_ids=[
            "internship",
            "summer_internship",
            "seasonal_job",
            "co_op",
            "trainee",
            "entry_level",
            "research",
            "apprentice",
        ],
        preferred_workplace_types=["remote", "hybrid", "onsite"],
        preferred_countries=[],
        max_distance_km=None,
        allow_unknown_distance=True,
        minimum_score=40,
    ),
}
