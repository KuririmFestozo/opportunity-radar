# 🎯 Opportunity Radar v3.3

O projeto agora é um **motor genérico de oportunidades**, não um radar fixo de Engenharia Elétrica.

## A mudança mais importante

A vaga é coletada uma vez e classificada independentemente por curso e tipo de oportunidade.
Depois, cada **perfil de busca** decide se aquela vaga faz sentido para aquele usuário.

Exemplo:

```text
Hardware Intern

Engenharia Elétrica: 92%
Ciência da Computação: 61%
Engenharia Mecânica: 17%
```

A mesma vaga pode, portanto, aparecer para pessoas diferentes com scores diferentes.

## Filtros já preparados

O dashboard da v3 permite filtrar por:

- perfil de busca;
- curso/área;
- estágio, summer internship, co-op, trainee, pesquisa etc.;
- fonte;
- remoto, híbrido ou presencial;
- score mínimo;
- distância máxima em km;
- localização atual do dispositivo;
- texto livre: empresa, cargo, cidade etc.

## Localização e distância

As localidades textuais das vagas são resolvidas localmente com `geonamescache`.
Isso dá coordenadas aproximadas do **centro da cidade**, suficientes para filtros do tipo:

```text
até 25 km
até 50 km
até 100 km
até 250 km
```

Não é uma estimativa porta a porta nem de tempo de trânsito.

No dashboard, você também pode clicar em:

```text
📍 Usar minha localização
```

Sua posição atual é usada apenas no navegador para recalcular as distâncias exibidas.
A v3 não envia essa posição para nenhum servidor.

Para o navegador permitir geolocalização, rode a página em localhost:

```powershell
cd output
python -m http.server 8000
```

Depois abra:

```text
http://localhost:8000
```

## Cursos iniciais

- Engenharia Elétrica
- Ciência da Computação
- Engenharia Mecânica
- Engenharia Civil
- Engenharia de Produção
- Administração
- Ciência de Dados

Eles ficam em:

```text
config/catalogs.py
```

Adicionar um curso novo é configuração, não exige um novo coletor.

## Intenções iniciais

- Estágio
- Summer Internship
- Co-op
- Trainee
- Júnior / Entry Level
- Pesquisa / Research
- Aprendiz

## Perfis de busca

Ficam em:

```text
config/profiles.py
```

Exemplo:

```python
SearchProfile(
    id="mechanical_nearby",
    name="Mecânica até 50 km",
    course_ids=["mechanical_engineering"],
    intent_ids=["internship"],
    include_keywords=["automotivo"],
    exclude_keywords=["vendas"],
    preferred_workplace_types=["hybrid", "onsite"],
    home_city="Campinas - SP",
    max_distance_km=50,
    allow_unknown_distance=False,
    minimum_score=50,
)
```

## Fontes

A v3 mantém:

- Lever
- Greenhouse
- Ashby
- Gupy pública
- Gupy API opcional
- Vagas.com
- CIEE
- 99jobs
- LinkedIn como links de busca, sem scraping

O Vagas.com passa a receber consultas geradas dinamicamente pelos cursos dos perfis ativos.

## Como rodar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Arquivos gerados

```text
output/
├── jobs.json
├── jobs.csv
├── profiles.json
├── matches.json
├── search_links.json
├── stats.json
├── dashboard_data.json
└── index.html
```

## Estrutura escalável para Supabase

`database/schema.sql` traz um desenho inicial multiusuário com PostGIS:

- `opportunities`: vaga única;
- `search_profiles`: preferências de cada usuário;
- `opportunity_course_scores`: afinidade vaga × curso;
- `opportunity_intents`: tipos detectados;
- coluna geográfica indexada para busca por proximidade.

No produto final, o celular não precisa comparar a posição com milhares de vagas: o banco pode retornar apenas as oportunidades próximas.

## Próxima arquitetura

```text
             Fontes de vagas
                  ↓
             Collectors
                  ↓
        Opportunity normalizada
                  ↓
     Classificação curso/intenção
                  ↓
         Supabase + PostGIS
           ↓             ↓
      Perfil A        Perfil B
   Elétrica 50 km   Computação remoto
           ↓             ↓
             Expo / app
```

O próximo passo natural é substituir `config/profiles.py` por perfis criados na interface e persistidos no Supabase, com login, favoritos e histórico de candidaturas.

## v3.1 — correções de robustez

- `preferred_countries` agora é aplicado no matching quando o país da vaga é conhecido.
- Intenção de estágio/trainee/co-op é inferida principalmente pelo título/tipo da vaga, evitando falsos positivos por boilerplate da descrição.
- Requisições possuem retry automático para falhas temporárias de DNS/conexão e erros 429/5xx.
- Parser do Vagas.com ignora fragmentos inválidos como `em` ao tentar identificar a empresa.


## v3.2 — Summer, Co-op, Trainee, Aprendiz e Pesquisa

A coleta e o matching agora tratam `intent` como uma dimensão real do sistema.

Perfis prontos incluídos:

- Engenharia Elétrica — Estágio no Brasil
- Engenharia Elétrica — Summer Internship / Co-op (EUA)
- Engenharia Elétrica — Todas as oportunidades
- Computação — Estágio no Brasil
- Computação — Todas as oportunidades

O perfil **Todas as oportunidades** inclui:

- Estágio
- Summer Internship
- Co-op
- Trainee / Graduate Program
- Júnior / Entry Level
- Pesquisa / Research
- Aprendiz

As buscas públicas brasileiras agora são geradas a partir da combinação
**curso × intenção**. Assim, um perfil que inclui trainee e aprendiz gera
consultas como `trainee engenharia elétrica` e `jovem aprendiz engenharia elétrica`,
em vez de pesquisar somente por `estágio`.

Summer/Co-op são principalmente internacionais e aparecem especialmente
nas fontes ATS (Lever/Ashby/Greenhouse) e nos links de busca externa.


## v3.3 — Collect first, filter later

A coleta não depende mais dos perfis ativos.

O backend tenta construir uma base ampla contendo:
- estágio;
- programa de estágio;
- estágio de verão;
- estágio de férias;
- summer internship;
- summer job / trabalho sazonal;
- co-op;
- trainee / graduate program;
- júnior / entry level;
- pesquisa / iniciação científica;
- aprendiz / jovem aprendiz.

No Brasil, `Summer Internship` também reconhece:
- Estágio de Verão;
- Programa de Estágio de Verão;
- Estágio de Férias;
- Programa de Estágio de Férias;
- Programa de Férias.

O dashboard agora inicia em:

```text
🌐 Explorar tudo
```

Sem filtro de curso, intenção ou país.

Depois o usuário pode aplicar os filtros que quiser.

### Coleta de Vagas.com

As consultas são geradas globalmente em `processing/collection_planner.py`,
independentemente dos perfis configurados.

Perfis continuam existindo somente como presets de filtro/matching.

### Observação

Nenhum agregador consegue garantir literalmente "todas as vagas da internet".
A arquitetura da v3.3, porém, evita perder uma vaga apenas porque o perfil ativo
não tinha o curso, país ou intenção correspondente.
