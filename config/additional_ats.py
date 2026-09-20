# Additional public ATS boards used by Opportunity Radar.
#
# These are source-level collection scopes. They are intentionally independent
# from user profiles/courses: collect once, classify/filter later.

EARLY_CAREER_QUERIES = [
    "estágio",
    "estagiário",
    "intern",
    "internship",
    "summer",
    "trainee",
    "aprendiz",
    "apprentice",
    "junior",
    "júnior",
    "entry level",
    "new grad",
    "graduate",
    "co-op",
    "working student",
    "research",
    "thesis",
]

INHIRE_TENANTS = [
    {
        "id": "elogroup",
        "name": "EloGroup",
        "tenant": "elogroup",
        "enabled": True,
        "max_jobs": 500,
    },
]

IZIRH_TENANTS = [
    {
        "id": "embraer",
        "name": "Embraer",
        "subdomain": "embraer.izirh.io",
        "enabled": True,
        "max_jobs": 500,
    },
    {
        "id": "programasembraer",
        "name": "Embraer Programas",
        "subdomain": "programasembraer.izirh.io",
        "enabled": True,
        "max_jobs": 500,
    },
]

WORKDAY_BOARDS = [
    {
        "id": "hitachi",
        "name": "Hitachi",
        "board_url": "https://hitachi.wd1.myworkdayjobs.com/en-US/hitachi",
        "enabled": True,
        "queries": EARLY_CAREER_QUERIES,
        "max_pages_per_query": 3,
        "max_jobs": 350,
    },
]

SMARTRECRUITERS_BOARDS = [
    {
        "id": "bosch",
        "name": "Bosch Group",
        "company_identifier": "BoschGroup",
        "enabled": True,
        "queries": EARLY_CAREER_QUERIES,
        "max_pages_per_query": 2,
        "max_jobs": 250,
    },
    {
        "id": "aumovio",
        "name": "Aumovio",
        "company_identifier": "Aumovio",
        "enabled": True,
        "queries": EARLY_CAREER_QUERIES,
        "max_pages_per_query": 2,
        "max_jobs": 250,
    },
]

INHIRE_TENANTS.append({"id": "magazineluiza", "name": "Magazine Luiza", "tenant": "magazineluiza", "enabled": True, "max_jobs": 500})

INHIRE_TENANTS.append({"id": "willbank", "name": "Will Bank", "tenant": "willbank", "enabled": True, "max_jobs": 500})

INHIRE_TENANTS.append({"id": "nomadglobal", "name": "Nomad", "tenant": "nomadglobal", "enabled": True, "max_jobs": 500})

INHIRE_TENANTS.append({"id": "kiwify", "name": "Kiwify", "tenant": "kiwify", "enabled": True, "max_jobs": 500})

INHIRE_TENANTS.append({"id": "semantix", "name": "Semantix", "tenant": "semantix", "enabled": True, "max_jobs": 500})

INHIRE_TENANTS.append({"id": "alice", "name": "Alice", "tenant": "alice", "enabled": True, "max_jobs": 500})

INHIRE_TENANTS.append({"id": "involves", "name": "Involves", "tenant": "involves", "enabled": True, "max_jobs": 500})

IZIRH_TENANTS.append({"id": "ems", "name": "EMS", "subdomain": "ems.izirh.io", "enabled": True, "max_jobs": 500})

IZIRH_TENANTS.append({"id": "cellerafarma", "name": "Cellera Farma", "subdomain": "cellerafarma.izirh.io", "enabled": True, "max_jobs": 500})

WORKDAY_BOARDS.append({
    "id": "mastercard", "name": "Mastercard Campus",
    "board_url": "https://mastercard.wd1.myworkdayjobs.com/en-US/Campus",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 3, "max_jobs": 350,
})

WORKDAY_BOARDS.append({
    "id": "roche", "name": "Roche",
    "board_url": "https://roche.wd3.myworkdayjobs.com/en-US/roche-ext",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 3, "max_jobs": 350,
})

WORKDAY_BOARDS.append({
    "id": "santander", "name": "Santander",
    "board_url": "https://santander.wd3.myworkdayjobs.com/en-US/SantanderCareers",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 3, "max_jobs": 350,
})

WORKDAY_BOARDS.append({
    "id": "db", "name": "Deutsche Bank",
    "board_url": "https://db.wd3.myworkdayjobs.com/en-US/DBWebsite",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 3, "max_jobs": 350,
})

WORKDAY_BOARDS.append({
    "id": "edenpeople", "name": "Edenred",
    "board_url": "https://edenpeople.wd3.myworkdayjobs.com/en-US/Edenred_Careers",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 3, "max_jobs": 350,
})

WORKDAY_BOARDS.append({
    "id": "erm", "name": "ERM",
    "board_url": "https://erm.wd3.myworkdayjobs.com/en-US/ERM_Careers",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 3, "max_jobs": 350,
})

WORKDAY_BOARDS.append({
    "id": "hbfuller", "name": "H.B. Fuller",
    "board_url": "https://hbfuller.wd1.myworkdayjobs.com/en-US/Careers",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 3, "max_jobs": 350,
})

WORKDAY_BOARDS.append({
    "id": "medtronic", "name": "Medtronic",
    "board_url": "https://medtronic.wd1.myworkdayjobs.com/en-US/MedtronicCareers",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 3, "max_jobs": 350,
})

SMARTRECRUITERS_BOARDS.append({
    "id": "continental", "name": "Continental", "company_identifier": "Continental",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 2, "max_jobs": 250,
})

SMARTRECRUITERS_BOARDS.append({
    "id": "louisdreyfuscompany", "name": "Louis Dreyfus Company", "company_identifier": "LouisDreyfusCompany",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 2, "max_jobs": 250,
})

SMARTRECRUITERS_BOARDS.append({
    "id": "jitterbit", "name": "Jitterbit", "company_identifier": "Jitterbit",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 2, "max_jobs": 250,
})

SMARTRECRUITERS_BOARDS.append({
    "id": "rotork1", "name": "Rotork", "company_identifier": "Rotork1",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 2, "max_jobs": 250,
})

SMARTRECRUITERS_BOARDS.append({
    "id": "veoliaenvironnementsa", "name": "Veolia", "company_identifier": "VeoliaEnvironnementSA",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 2, "max_jobs": 250,
})

SMARTRECRUITERS_BOARDS.append({
    "id": "syntegon", "name": "Syntegon", "company_identifier": "SYNTEGON",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 2, "max_jobs": 250,
})

SMARTRECRUITERS_BOARDS.append({
    "id": "applusidiada1", "name": "Applus IDIADA", "company_identifier": "ApplusIDIADA1",
    "enabled": True, "queries": EARLY_CAREER_QUERIES,
    "max_pages_per_query": 2, "max_jobs": 250,
})

# Regional priority; collect the public catalog, regardless of course or profile.
SMARTRECRUITERS_BOARDS.insert(0, {
    "id": "experian", "name": "Serasa Experian", "company_identifier": "Experian",
    "enabled": True, "queries": [], "max_pages_per_query": 20, "max_jobs": 2000,
})

TOTVS_TENANTS = [
    {"id": "xmobots", "name": "Xmobots", "tenant": "xmobotscarreiras",
     "enabled": True, "max_jobs": 500, "max_details": 100},
]

TEAMTAILOR_BOARDS = [
    {"id": "tecumseh", "name": "Tecumseh", "career_url": "https://careers.tecumseh.com",
     "enabled": True, "max_pages": 10, "max_jobs": 500, "max_details": 100},
]

# Product-level scope only; regional Experian deliberately retains its full catalog.
for board in WORKDAY_BOARDS + SMARTRECRUITERS_BOARDS:
    if board["id"] != "experian":
        board["early_career_only"] = True

# The public Phenom career site links to this Workday board; do not duplicate it.
WORKDAY_BOARDS.append({
    "id": "electrolux", "name": "Electrolux",
    "board_url": "https://electrolux.wd3.myworkdayjobs.com/en-US/ElectroluxCareerSite",
    "enabled": True, "queries": [], "early_career_only": False,
    "max_pages_per_query": 20, "max_jobs": 500,
})

# CP2-final: no product truncation for query-scoped ATS.
# Collectors still keep high guard rails against broken pagination.
for _board in WORKDAY_BOARDS:
    _board["max_pages_per_query"] = 0
    _board["max_jobs"] = 0

for _board in SMARTRECRUITERS_BOARDS:
    _board["max_pages_per_query"] = 0
    _board["max_jobs"] = 0
