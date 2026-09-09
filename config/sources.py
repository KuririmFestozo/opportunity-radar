PUBLIC_SOURCES = {
    "gupy_global": {
        "enabled": True,
        "page_size": 100,
        # Broad but bounded: up to 800 newest jobs for each native type.
        "max_pages_per_native_type": 12,
        # Extra passes for types without a dedicated Gupy vacancy type.
        "max_pages_per_keyword": 2,
        "native_job_types": [
            "vacancy_type_internship",
            "vacancy_type_summer",
            "vacancy_type_trainee",
            "vacancy_type_apprentice",
        ],
        "keyword_queries": [
            "junior",
            "júnior",
            "entry level",
            "new grad",
            "graduate engineer",
            "co-op",
            "research",
            "iniciação científica",
            "summer job",
            "trabalho de férias",
        ],
        # On-demand regional search: exact city passes prevent local jobs from
        # being buried behind thousands of national results.
        "nearby_max_pages_per_city": 2,
        "nearby_keyword_city_limit": 4,
        "nearby_keyword_queries": ["junior", "co-op", "research"],
    },
    "regional_search": {
        "max_cities": 24,
        "vagas_com_enabled": True,
        "vagas_com_city_limit": 4,
        "vagas_com_max_jobs_per_query": 40,
        "vagas_com_queries": [
            "estagio",
            "trainee",
            "jovem aprendiz",
            "junior",
        ],
    },
    # Kept only as an emergency fallback if the public portal API changes.
    "gupy_public_fallback": {
        "enabled": False,
    },
    "vagas_com": {
        "enabled": True,
        "max_jobs_per_query": 80,
        "max_collection_queries": 60,
    },
    "ciee": {
        "enabled": True,
        "max_jobs": 200,
    },
    "jobs99": {
        "enabled": True,
        "max_jobs": 150,
    },
}

GUPY_PUBLIC_PAGES = [
    {
        "name": "WEG - Estágio",
        "base_url": "https://wegestagio.gupy.io",
        "enabled": True,
        "max_details": 30,
    },
    {
        "name": "WEG",
        "base_url": "https://weg.gupy.io",
        "enabled": True,
        "max_details": 30,
    },
    {
        "name": "Aegea",
        "base_url": "https://aegea.gupy.io",
        "enabled": True,
        "max_details": 30,
    },
]
