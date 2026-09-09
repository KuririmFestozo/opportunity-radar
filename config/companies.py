# Empresas iniciais para validar o coletor.
# Podemos expandir bastante esta lista depois.
#
# ats:
#   - lever
#   - ashby
#   - greenhouse
#
# slug:
#   Lever  -> https://jobs.lever.co/{slug}
#   Ashby  -> https://jobs.ashbyhq.com/{slug}
#   Greenhouse -> token do job board público

COMPANIES = [
    # Lever
    {
        "name": "Shield AI",
        "ats": "lever",
        "slug": "shieldai",
        "enabled": True,
    },
    {
        "name": "Nexus Engineering Group",
        "ats": "lever",
        "slug": "nexuse-group",
        "enabled": True,
    },
    {
        "name": "Foth",
        "ats": "lever",
        "slug": "foth",
        "enabled": True,
    },

    # Ashby
    {
        "name": "Northwood Space",
        "ats": "ashby",
        "slug": "northwoodspace",
        "enabled": True,
    },
    {
        "name": "Etched",
        "ats": "ashby",
        "slug": "etched",
        "enabled": True,
    },
    {
        "name": "Persona AI",
        "ats": "ashby",
        "slug": "persona.ai",
        "enabled": True,
    },
    {
        "name": "Forge Atomics",
        "ats": "ashby",
        "slug": "forgeatomics",
        "enabled": True,
    },

    # Exemplo para adicionar Greenhouse:
    # {
    #     "name": "Empresa Greenhouse",
    #     "ats": "greenhouse",
    #     "slug": "board_token_aqui",
    #     "enabled": False,
    # },
]
