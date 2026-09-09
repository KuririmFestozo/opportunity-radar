# 🎯 Opportunity Radar v3.4

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

Na v3.5, sua posição pode ser enviada para o **servidor local** do radar em `localhost` quando você usa a busca regional ao vivo. As fontes externas recebem consultas por cidade; o radar não precisa enviar suas coordenadas exatas para a Gupy/Vagas.com.

Para habilitar geolocalização e a busca sob demanda, rode o app local:

```powershell
python server.py
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
python server.py
```

Depois abra `http://localhost:8000`. O `main.py` atualiza a base ampla; o `server.py` serve o dashboard e expõe a busca regional sob demanda.

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


## v3.4 — Gupy Global + dashboard renovado

A coleta da Gupy agora usa o endpoint JSON consumido pelo portal público de candidatos, em vez de depender normalmente de páginas de empresas específicas.

A estratégia da Gupy Global é:

- coletar tipos nativos de início de carreira (`internship`, `summer`, `trainee`, `apprentice`) sem filtrar por curso ou cidade;
- fazer buscas adicionais para `junior`, `entry level`, `new grad`, `co-op`, pesquisa e summer jobs;
- paginar em lotes de até 100 vagas, com limites configuráveis em `config/sources.py`;
- classificar por curso, intenção, país e distância somente depois da coleta;
- manter `gupy_public.py` como fallback, desativado por padrão.

O tipo estruturado da Gupy passa a ser usado pela classificação. Isso evita perder vagas com títulos genéricos como `Programa 2027` quando a própria Gupy informa que a vaga é `vacancy_type_summer` ou `vacancy_type_internship`.

> Observação: o endpoint global é o usado pelo portal público e pode mudar. A API oficial autenticada (`gupy_api.py`) continua separada e opcional.

### Dashboard

O dashboard foi redesenhado com:

- busca principal em destaque;
- cards de métricas;
- chips de tipos de oportunidade;
- painel lateral de filtros;
- cards de vaga com relevância, modalidade, cursos, distância e data;
- layout responsivo para notebook e celular;
- botão para limpar todos os filtros.

Os arquivos de `output/` continuam locais e ignorados pelo Git. No GitHub Actions, o dashboard gerado é publicado como artifact temporário em vez de ser commitado no repositório.


## v3.5 — radar regional sob demanda

O dashboard agora pode pedir uma nova busca depois que a coleta principal terminou.

Fluxo:

```text
Dashboard
  ↓ POST /api/search
FastAPI local
  ├─ filtra a base já coletada pelo raio
  ├─ descobre cidades dentro do raio com GeoNames
  ├─ consulta a Gupy por cidade
  ├─ faz buscas regionais complementares no Vagas.com
  ├─ normaliza, classifica e geocodifica os resultados novos
  ├─ deduplica com a base existente
  └─ aplica o raio real em km
       ↓
Dashboard recebe e incorpora os resultados
```

A busca regional usa cache em memória por 30 minutos por padrão (`NEARBY_SEARCH_CACHE_SECONDS=1800`) para evitar repetir as mesmas requisições. O botão **ignorar cache na próxima busca** força uma atualização.

O raio aceito pela API vai de 5 a 250 km. A quantidade de cidades consultadas e o número de páginas por cidade ficam limitados em `config/sources.py` para manter a busca regional útil sem transformar cada clique em uma varredura nacional.

Endpoints locais:

- `GET /api/health`
- `GET /api/jobs`
- `GET /api/jobs/nearby` — somente base existente
- `POST /api/search` — base existente + coleta externa regional
- `GET /api/stats`

> O endpoint público do portal da Gupy é tratado como uma integração defensiva e pode mudar. A busca regional mantém a mesma separação da v3.4 entre o portal público e a API oficial autenticada.
