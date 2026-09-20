COURSES = {
    "electrical_engineering": {
        "label": "Engenharia Elétrica",
        "core_terms": [
            "engenharia elétrica", "engenharia eletrica", "electrical engineering",
            "electrical engineer", "engenheiro elétrico", "engenheiro eletrico",
            "power systems", "power electronics", "electrical systems",
        ],
        "related_terms": [
            "eletrônica", "eletronica", "electronics", "embedded", "sistemas embarcados",
            "firmware", "hardware", "pcb", "fpga", "asic", "rf", "signal processing",
            "automação", "automacao", "automation", "controle", "control systems",
            "instrumentação", "instrumentacao", "robotics", "robótica", "robotica",
            "mecatrônica", "mecatronica", "energy", "energia", "renewable", "battery",
            "semiconductor", "avionics", "telecommunications", "telecom", "plc",
        ],
        "search_terms_pt": ["engenharia elétrica", "engenharia eletrônica", "automação", "sistemas embarcados", "energia"],
        "search_terms_en": ["electrical engineering", "electronics engineering", "hardware engineering", "embedded systems", "power systems"],
    },
    "computer_science": {
        "label": "Ciência da Computação",
        "core_terms": [
            "ciência da computação", "ciencia da computacao", "computer science",
            "software engineering", "engenharia de software", "software engineer",
            "software developer", "desenvolvedor", "desenvolvedora",
        ],
        "related_terms": [
            "backend", "back-end", "frontend", "front-end", "full stack", "fullstack",
            "python", "java", "javascript", "typescript", "cloud", "devops", "mobile",
            "machine learning", "data science", "cybersecurity", "segurança da informação",
            "computer vision", "artificial intelligence", "inteligência artificial", "banco de dados",
        ],
        "search_terms_pt": ["ciência da computação", "desenvolvimento de software", "engenharia de software", "dados", "inteligência artificial"],
        "search_terms_en": ["computer science", "software engineering", "software developer", "machine learning", "data science"],
    },
    "mechanical_engineering": {
        "label": "Engenharia Mecânica",
        "core_terms": ["engenharia mecânica", "engenharia mecanica", "mechanical engineering", "mechanical engineer", "engenheiro mecânico", "engenheiro mecanico"],
        "related_terms": ["cad", "cae", "solidworks", "catia", "ansys", "thermodynamics", "termodinâmica", "termodinamica", "fluids", "mecânica dos fluidos", "manutenção", "manutencao", "manufacturing", "manufatura", "process engineering", "automotive", "aerospace", "hvac"],
        "search_terms_pt": ["engenharia mecânica", "manutenção", "projetos mecânicos", "manufatura", "processos"],
        "search_terms_en": ["mechanical engineering", "mechanical design", "manufacturing engineering", "automotive engineering", "aerospace engineering"],
    },
    "civil_engineering": {
        "label": "Engenharia Civil",
        "core_terms": ["engenharia civil", "civil engineering", "civil engineer", "engenheiro civil"],
        "related_terms": ["construction", "construção", "construcao", "structures", "estruturas", "geotechnical", "geotecnia", "bim", "revit", "autocad", "infrastructure", "infraestrutura", "orçamento", "orcamento", "planejamento de obras"],
        "search_terms_pt": ["engenharia civil", "construção civil", "obras", "estruturas", "bim"],
        "search_terms_en": ["civil engineering", "construction engineering", "structural engineering", "infrastructure", "bim"],
    },
    "production_engineering": {
        "label": "Engenharia de Produção",
        "core_terms": ["engenharia de produção", "engenharia de producao", "industrial engineering", "production engineering"],
        "related_terms": ["process improvement", "melhoria contínua", "melhoria continua", "lean", "six sigma", "operations", "operações", "operacoes", "supply chain", "logística", "logistica", "quality", "qualidade", "planning", "planejamento"],
        "search_terms_pt": ["engenharia de produção", "processos", "qualidade", "logística", "operações"],
        "search_terms_en": ["industrial engineering", "production engineering", "operations", "supply chain", "quality engineering"],
    },
    "administration": {
        "label": "Administração",
        "core_terms": ["administração", "administracao", "business administration", "business"],
        "related_terms": ["finance", "finanças", "financas", "marketing", "sales", "vendas", "operations", "operações", "operacoes", "procurement", "compras", "human resources", "recursos humanos", "strategy", "estratégia", "estrategia", "commercial", "comercial"],
        "search_terms_pt": ["administração", "finanças", "marketing", "comercial", "operações"],
        "search_terms_en": ["business administration", "business", "finance", "marketing", "operations"],
    },
    "data_science": {
        "label": "Ciência de Dados",
        "core_terms": ["data science", "ciência de dados", "ciencia de dados", "data scientist", "cientista de dados", "machine learning"],
        "related_terms": ["python", "sql", "statistics", "estatística", "estatistica", "analytics", "análise de dados", "analise de dados", "business intelligence", "deep learning", "computer vision", "nlp", "artificial intelligence", "inteligência artificial"],
        "search_terms_pt": ["ciência de dados", "dados", "machine learning", "analytics", "inteligência artificial"],
        "search_terms_en": ["data science", "data analyst", "machine learning", "analytics", "artificial intelligence"],
    },
}



INTENTS = {
    "internship": {
        "label": "Estágio",
        "terms": [
            "estágio", "estagio", "estagiário", "estagiario",
            "intern", "internship",
        ],
        "search_prefixes_pt": [
            "estagio",
            "programa de estagio",
        ],
        "search_suffixes_en": ["intern", "internship"],
    },

    "summer_internship": {
        "label": "Summer / Estágio de Férias",
        "terms": [
            "summer intern",
            "summer internship",
            "summer engineering intern",
            "estágio de verão",
            "estagio de verao",
            "programa de estágio de verão",
            "programa de estagio de verao",
            "estágio de férias",
            "estagio de ferias",
            "programa de estágio de férias",
            "programa de estagio de ferias",
            "programa de férias",
            "programa de ferias",
            "programa de verão",
            "programa de verao",
            "vacation internship",
            "vacation intern",
        ],
        "search_prefixes_pt": [
            "estagio de verao",
            "programa de estagio de verao",
            "estagio de ferias",
            "programa de estagio de ferias",
            "programa de ferias",
            "summer internship",
        ],
        "search_suffixes_en": [
            "summer intern",
            "summer internship",
        ],
    },

    "seasonal_job": {
        "label": "Summer Job / Temporário de Férias",
        "terms": [
            "summer job",
            "seasonal job",
            "seasonal work",
            "seasonal worker",
            "temporary summer",
            "temporary job",
            "trabalho temporário de verão",
            "trabalho temporario de verao",
            "trabalho de férias",
            "trabalho de ferias",
            "vaga temporária de verão",
            "vaga temporaria de verao",
            "trabalho temporário de férias",
            "trabalho temporario de ferias",
            "vaga de férias",
            "vaga de ferias",
            "vaga temporária de férias",
            "vaga temporaria de ferias",
        ],
        "search_prefixes_pt": [
            "summer job",
            "trabalho de ferias",
            "trabalho temporario de verao",
            "vaga temporaria de verao",
        ],
        "search_suffixes_en": [
            "summer job",
            "seasonal job",
        ],
    },

    "co_op": {
        "label": "Co-op",
        "terms": ["co-op", "coop", "co op"],
        "search_prefixes_pt": ["co-op", "coop"],
        "search_suffixes_en": ["co-op", "coop"],
    },

    "trainee": {
        "label": "Trainee / Graduate Program",
        "terms": [
            "trainee", "graduate program", "graduate programme",
            "programa trainee", "programa de trainee",
        ],
        "search_prefixes_pt": ["trainee", "programa trainee"],
        "search_suffixes_en": ["graduate program", "graduate programme"],
    },

    "entry_level": {
        "label": "Júnior / Entry Level",
        "terms": [
            "junior", "júnior", "entry level", "entry-level",
            "new grad", "new graduate", "graduate engineer",
            "early career", "early careers",
        ],
        "search_prefixes_pt": ["junior"],
        "search_suffixes_en": ["entry level", "new grad", "early career"],
    },

    "research": {
        "label": "Pesquisa / Research",
        "terms": [
            "research intern", "research internship",
            "undergraduate research", "research assistant",
            "pesquisa", "iniciação científica", "iniciacao cientifica",
        ],
        "search_prefixes_pt": [
            "pesquisa",
            "iniciacao cientifica",
            "estagio pesquisa",
        ],
        "search_suffixes_en": [
            "research intern",
            "undergraduate research",
        ],
    },

    "apprentice": {
        "label": "Aprendiz",
        "terms": [
            "aprendiz", "jovem aprendiz", "apprentice", "apprenticeship",
        ],
        "search_prefixes_pt": ["aprendiz", "jovem aprendiz"],
        "search_suffixes_en": ["apprentice", "apprenticeship"],
    },
}


NEGATIVE_SENIORITY = [
    "senior", "sênior", "staff", "principal",
    "manager", "gerente", "director", "diretor",
    "lead ", "líder", "lider", "head of",
    "vice president", "vp ", "especialista",
]
