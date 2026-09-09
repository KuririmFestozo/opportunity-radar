PUBLIC_SOURCES = {
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
