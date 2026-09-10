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
    "summer_br": {
        "enabled": True,
        # Rare opportunity class: run dedicated discovery passes in addition
        # to the broad collectors.
        "gupy_enabled": True,
        "jobs99_enabled": True,
        "vagas_com_enabled": True,
        "summer_native_pages": 8,
        "summer_keyword_pages": 3,
        "jobs99_pages_per_term": 4,
        "jobs99_max_jobs": 700,
        "vagas_max_jobs_per_query": 80,
    },
    "regional_search": {
        "max_cities": 24,
        "vagas_com_enabled": True,
        "jobs99_enabled": True,
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
        "max_jobs": 2500,
        "nearby_max_cities": 6,
        "nearby_max_pages_per_query": 1,
        "nearby_max_jobs": 400,
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

CORPORATE_ATS_SOURCES = [
    {
        "name": "Ternium",
        "ats": "successfactors",
        "enabled": True,
        "listing_url": "https://carrera.ternium.com/go/Nossas-Oportunidades/8723700/",
        # Empty query walks the catalog; focused terms reinforce rare early-career jobs.
        "queries": [
            "",
            "estágio de verão",
            "estágio de férias",
            "programa de férias",
            "summer internship",
            "estágio",
            "trainee",
        ],
        "page_size": 25,
        "max_pages_per_query": 4,
        "max_jobs": 120,
        "max_details": 30,
    },
]
