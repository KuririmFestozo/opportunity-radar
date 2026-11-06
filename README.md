# 🎯 Opportunity Radar

O **Opportunity Radar** é um agregador inteligente de oportunidades de início de carreira.

A proposta é reunir vagas publicadas em diferentes plataformas, normalizar os dados, classificar cada oportunidade por **curso/área** e **tipo de vaga**, acompanhar o ciclo de vida dos anúncios e permitir que diferentes perfis encontrem o que faz sentido para eles sem limitar a coleta na origem.

> **Estado atual:** Checkpoint 4 concluído — persistência relacional unificada e sincronização segura do estado do servidor validadas.
> **Próximo passo:** Checkpoint 5 — PostgreSQL / Supabase / PostGIS.

---

## Por que este projeto existe?

Vagas de estágio, trainee, júnior, pesquisa e programas universitários ficam espalhadas entre dezenas de plataformas e páginas corporativas.

Além disso:

- empresas publicam a mesma oportunidade em lugares diferentes;
- títulos de vaga nem sempre deixam claro quais cursos são aceitos;
- alguns portais removem vagas sem indicar explicitamente que foram encerradas;
- buscas por palavras-chave podem esconder oportunidades relevantes;
- cada plataforma usa formatos, identificadores e estruturas diferentes.

O Opportunity Radar tenta resolver isso criando **um catálogo único e pesquisável**, sem depender de um único portal.

---

## A proposta

O princípio central é simples:

> **Collect first, filter later.**

Os coletores tentam formar uma base ampla de oportunidades.
Curso, localização, intenção e perfil do usuário só entram **depois da coleta**.

Fluxo geral:

```mermaid
flowchart TD
    A[Fontes de vagas] --> B[Collectors]
    B --> C[Normalização]
    C --> D[Identidade e deduplicação]
    D --> E[Classificação]
    E --> F[Persistência incremental]
    F --> G[Perfis e filtros]
    G --> H[Dashboard / API]
```

Uma vaga é coletada uma vez e pode ser relevante para vários cursos ao mesmo tempo.

Exemplo:

```text
Hardware Intern

Engenharia Elétrica       92%
Engenharia de Computação  88%
Ciência da Computação     61%
Engenharia Mecânica       17%
```

---

## Princípios do projeto

### 1. Collect first, filter later

Perfis não controlam o que os collectors coletam.

Isso evita perder uma oportunidade apenas porque o perfil ativo naquele momento não incluía determinado curso, cidade ou tipo de vaga.

### 2. Identidade por fonte

A identidade primária de um anúncio é:

```text
(source, source_job_id)
```

Duas fontes diferentes não são tratadas como a mesma vaga sem evidência suficiente.

### 3. Deduplicação conservadora

Quando anúncios parecem representar a mesma oportunidade, o catálogo pode consolidá-los.

Mas, quando há dúvida, o sistema prefere manter duas entradas a esconder uma vaga legítima.

### 4. Lifecycle conservador

Uma vaga não é considerada encerrada só porque deixou de aparecer em uma execução parcial.

O ciclo atual é:

```text
active
  ↓  1ª ausência em varredura completa
missing
  ↓  2ª ausência consecutiva em varredura completa
inactive
```

Se a vaga reaparecer:

```text
inactive / missing → active
```

### 5. Automação reprodutível

Execuções locais são rápidas e incrementais.

O GitHub Actions executa auditorias mais pesadas, persiste o SQLite entre runs e mantém snapshots temporários para recuperação.

---

## O que o Opportunity Radar já faz

| Área | Estado |
|---|---|
| Coleta multi-fonte | ✅ |
| Normalização de vagas | ✅ |
| Classificação por curso | ✅ |
| Classificação por tipo de oportunidade | ✅ |
| Deduplicação conservadora | ✅ |
| Geocodificação aproximada por cidade | ✅ |
| Busca por distância | ✅ |
| Perfis de busca | ✅ |
| Dashboard local | ✅ |
| Busca regional sob demanda | ✅ |
| Persistência incremental em SQLite | ✅ |
| Lifecycle active / missing / inactive | ✅ |
| Auditoria diária no GitHub Actions | ✅ |
| Persistência relacional unificada | ✅ |
| PostgreSQL / Supabase / PostGIS | ⏳ |
| Usuários e perfis persistentes | ⏳ |
| Favoritos e candidaturas | ⏳ |
| Aplicativo mobile | ⏳ |

---

## Fontes

O projeto usa apenas integrações públicas ou configuráveis e mantém cada integração isolada em seu próprio collector.

### ATS e portais corporativos

Entre as integrações existentes estão:

- Gupy;
- Lever;
- Greenhouse;
- Ashby;
- SuccessFactors / SAP Career Site Builder;
- Workday;
- SmartRecruiters;
- Eightfold;
- InHire;
- IziRH;
- TOTVS Atração de Talentos;
- Teamtailor.

Há também boards e páginas corporativas específicas, como o catálogo universitário da Cargill.

### Fontes brasileiras de início de carreira

Atualmente há collectors ativos para:

- Vagas.com;
- 99jobs;
- WallJobs;
- Companhia de Estágios;
- Nube;
- IEL Carreiras;
- Super Estágios;
- TAQE;
- Bettha;
- Matchbox Brasil.

Algumas integrações podem ficar desabilitadas quando o portal não oferece uma rota pública suficientemente estável.

---

## Cursos e áreas

O sistema não foi projetado para um único curso.

Entre os cursos já modelados estão:

- Engenharia Elétrica;
- Engenharia Mecânica;
- Engenharia Civil;
- Engenharia de Produção;
- Engenharia Química;
- Engenharia de Materiais;
- Engenharia de Computação;
- Engenharia Física;
- Engenharia Agronômica;
- Engenharia Ambiental;
- Engenharia de Alimentos;
- Engenharia Florestal;
- Ciência da Computação;
- Ciência de Dados;
- Administração.

Os catálogos ficam em:

```text
config/catalogs.py
```

Adicionar um curso novo deve ser principalmente uma alteração de configuração e regras de afinidade — não a criação de um novo collector.

---

## Tipos de oportunidade

O radar reconhece diferentes intenções, incluindo:

- estágio;
- programa de estágio;
- summer internship;
- estágio de férias / verão;
- co-op;
- trainee / graduate program;
- júnior / entry level;
- aprendiz / jovem aprendiz;
- pesquisa / iniciação científica;
- oportunidades sazonais.

---

## Perfis de busca

Perfis são presets de filtro e matching.

Eles ficam em:

```text
config/profiles.py
```

Exemplos atuais incluem:

- Engenharia Elétrica — Estágio no Brasil;
- Ciência da Computação — Estágio no Brasil;
- Engenharia Química — Estágio no Brasil;
- Engenharias UFSCar — Estágio no Brasil;
- perfis internacionais para summer internship / co-op.

Um perfil pode combinar:

- um ou mais cursos;
- tipos de oportunidade;
- palavras incluídas ou excluídas;
- modalidade de trabalho;
- países;
- cidade de referência;
- distância máxima;
- score mínimo.

Perfis **não limitam a coleta**.

---

## Arquitetura atual

```mermaid
flowchart LR
    A[Collectors] --> B[Job normalizado]
    B --> C[Classificação]
    C --> D[SQLite]
    D --> E[Deduplicação de catálogo]
    E --> F[JSON / CSV]
    E --> G[Dashboard]
    D --> H[API local]
```

Hoje o SQLite mantém:

- anúncios coletados;
- hashes para processamento incremental;
- timestamps de primeira e última visualização;
- lifecycle;
- memória de discovery;
- estado das auditorias por source/scope.

O **Checkpoint 4** reorganiza essa persistência para separar explicitamente a oportunidade consolidada dos anúncios de origem.

---

## Modos de execução

### Execução local normal

```powershell
python main.py
```

Modo incremental e mais rápido.

Reutiliza IDs e detalhes conhecidos sempre que possível.

### Descoberta completa

```powershell
$env:FULL_DISCOVERY="1"
python main.py
```

Desabilita early-stops de discovery para reconstruir uma visão completa dos escopos configurados.

### Full refresh

```powershell
$env:FULL_REFRESH="1"
python main.py
```

Além da descoberta completa, força atualização de detalhes conhecidos.

É o modo mais pesado e deve ser usado principalmente para rebuild/debug.

### Auditoria diária

O GitHub Actions roda automaticamente com:

```text
DAILY_AUDIT=1
UNBOUNDED_COLLECTION=1
```

Nesse modo:

- restaura o SQLite do run anterior;
- percorre os escopos configurados sem early-stop;
- mantém guard rails técnicos contra paginação quebrada;
- reconcilia lifecycle apenas quando a cobertura pode ser provada como completa;
- salva o SQLite atualizado somente após sucesso;
- publica snapshots temporários como artifacts.

---

## Como rodar localmente

### Windows / PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python main.py
python server.py
```

Depois abra:

```text
http://localhost:8000
```

O `main.py` atualiza a base.

O `server.py` inicia a API/dashboard local e habilita a busca regional sob demanda.

---

## Dashboard e localização

O dashboard permite filtrar por:

- perfil;
- curso;
- intenção;
- fonte;
- modalidade;
- score mínimo;
- distância;
- texto livre.

A geolocalização das vagas é aproximada pelo centro da cidade.

Ela é suficiente para filtros como:

```text
25 km
50 km
100 km
250 km
```

Não representa distância porta a porta nem tempo de deslocamento.

A busca regional ao vivo usa cidades próximas como consultas externas. Coordenadas exatas não precisam ser enviadas às fontes de vagas.

---

## Persistência incremental

O armazenamento atual fica em:

```text
data/opportunity_radar.db
```

O arquivo é local e não é versionado.

O sistema mantém:

- `jobs`;
- `discovery_state`;
- `collection_scopes`.

Execuções incompletas ou com erro não podem, por si só, inativar vagas.

Mais detalhes:

- [`docs/checkpoint-3.md`](docs/checkpoint-3.md)

---

## Arquivos gerados

A execução gera:

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

Esses arquivos são derivados da base e **não são versionados no Git**.

No GitHub Actions eles são publicados como artifacts temporários.

---

## Estrutura do repositório

```text
opportunity-radar/
├── api/                  # API FastAPI e busca regional
├── collectors/           # integrações com fontes de vagas
├── config/               # fontes, cursos, intenções e perfis
├── database/             # desenho do schema PostgreSQL futuro
├── docs/                 # documentação dos checkpoints
├── models/               # modelos de domínio
├── processing/           # classificação, localização e deduplicação
├── storage/              # persistência incremental
├── tests/                # testes automatizados
├── tools/                # utilitários de manutenção
├── output/               # artefatos gerados localmente
├── main.py               # pipeline principal
└── server.py             # servidor local
```

---

## Testes e validação

Suite principal:

```powershell
python -m pytest -q
```

Regressões estruturais:

```powershell
python check_project.py
```

Há também smoke tests específicos para fontes e checkpoints.

Exemplos:

```powershell
python validate_checkpoint3_sources.py
python validate_checkpoint31_sources.py
```

Smoke tests acessam fontes reais e, portanto, podem falhar temporariamente por timeout, rate limit ou indisponibilidade externa sem indicar uma regressão interna.

---

## Roadmap

| Etapa | Objetivo | Estado |
|---|---|---|
| CP1 | Consistência do pipeline | ✅ |
| CP2 | Identidade, deduplicação e expansão de fontes | ✅ |
| CP3 | Integridade incremental e lifecycle | ✅ |
| CP3.1 | Engenharias + expansão brasileira | ✅ |
| CP4 | Persistência unificada | ✅ |
| CP5 | PostgreSQL / Supabase / PostGIS | ⏳ |
| CP6 | API de catálogo | ⏳ |
| CP7 | Usuários e perfis persistentes | ⏳ |
| CP8 | Favoritos e candidaturas | ⏳ |
| CP9 | Experiência web definitiva | ⏳ |
| CP10 | Aplicativo Expo / mobile | ⏳ |

Roadmap detalhado:

- [`docs/roadmap.md`](docs/roadmap.md)

---

## Checkpoint atual

O Checkpoint 4 foi concluído e estabilizou o modelo relacional do catálogo.

O próximo trabalho arquitetural é:

### Checkpoint 5 — PostgreSQL / Supabase / PostGIS

Objetivos principais:

- portar o modelo estabilizado de `opportunities` e `source_postings` para PostgreSQL;
- preservar identidade, lifecycle, course scores, intents e associações cross-source;
- introduzir PostGIS para consultas geográficas;
- reduzir gradualmente a dependência do SQLite local sem reformular o domínio.

Referências:

- [`docs/checkpoint-4.md`](docs/checkpoint-4.md)
- [`docs/roadmap.md`](docs/roadmap.md)

---

## Limitações conhecidas

O Opportunity Radar não pretende garantir literalmente todas as vagas existentes na internet.

A cobertura depende de:

- disponibilidade pública das fontes;
- estabilidade dos endpoints;
- paginação;
- qualidade dos dados publicados;
- limites técnicos e rate limits externos.

Algumas fontes possuem APIs estruturadas; outras dependem de HTML público e exigem parsers defensivos.

Matching por curso é uma estimativa baseada em sinais textuais e estruturados — não substitui a leitura dos requisitos oficiais da vaga.

---

## Documentação técnica

- [Roadmap](docs/roadmap.md)
- [Checkpoint 3 — Incremental integrity](docs/checkpoint-3.md)
- [Checkpoint 4 — Persistência unificada](docs/checkpoint-4.md)
- [Checkpoint 2.7 — ATS adicionais](docs/checkpoint-2.7.md)
- [Checkpoint 2.9 — Fontes brasileiras](docs/checkpoint-2.9.md)
- [Fechamento do bloco 2.x](docs/checkpoint-2x-finalization.md)

---

## Visão de produto

A arquitetura de longo prazo é:

```mermaid
flowchart TD
    A[Fontes públicas] --> B[Collectors]
    B --> C[Catálogo persistente]
    C --> D[PostgreSQL + PostGIS]
    D --> E[API]
    E --> F[Web]
    E --> G[Mobile]
    D --> H[Perfis]
    D --> I[Favoritos]
    D --> J[Candidaturas]
```

A ideia é que o Opportunity Radar deixe de ser apenas um script de agregação e evolua para uma plataforma pessoal de descoberta e acompanhamento de oportunidades.


---

## Entrega 2 — Protótipo web Spring MVC (13/11/2026)

O projeto inclui uma interface Java independente em
[web-mvc/](web-mvc/README.md), criada para a disciplina. O Python continua
responsável por coletar e classificar as vagas. O Java lê uma cópia consistente
do banco SQLite e utiliza Spring Boot, Thymeleaf, Spring Data JPA e Hibernate
SQLiteDialect.

Funcionalidades: catálogo paginado, busca e filtros, detalhes, pontuações,
favoritos e acompanhamento CRUD de candidaturas persistidos via JPA.

Para preparar uma cópia segura e iniciar a versão web no Windows:

~~~powershell
python web-mvc/tools/prepare_sqlite_snapshot.py data/opportunity_radar.db web-mvc/radar-web.db
$env:RADAR_DB_PATH = (Resolve-Path web-mvc/radar-web.db).Path
cd web-mvc
mvn spring-boot:run
~~~

Abra http://localhost:8080. Requer JDK 17 e Maven.
O gerador de snapshot **não substitui** um arquivo já existente; para repetir,
informe outro nome de destino.

Sem o SQLite de produção, há um gerador de dados claramente fictícios
([instruções](web-mvc/README.md)) para demonstração offline.

Testes:

~~~powershell
python -m pytest -q
mvn -B -ntp -f web-mvc/pom.xml test
~~~

A interface agora possui login com usuário e senha (BCrypt), contas no SQLite
 e proteção CSRF. Ainda não inclui recuperação de senha; use o túnel Cloudflare
 apenas para testes temporários. O módulo não usa
Supabase nem modifica tabelas de coleta/lifecycle.



### Busca avançada e autenticação

A aplicação MVC inclui localização, raio, ordenação por proximidade ou
afinidade, filtros por curso, tipo e modalidade. Possui contas próprias
com usuário e senha: favoritos e candidaturas sincronizados entre aparelhos
que usam a mesma conta. Consulte [o guia](web-mvc/README.md).


### Baixar as vagas atualizadas para demonstração (SQLite)

O git pull atualiza apenas código. Para baixar o snapshot SQLite mais
recente do GitHub Actions, autenticado no repositório privado:

~~~powershell
gh auth login
python tools/pull_classroom_db.py
~~~

O comando salva em data/classroom_latest.db, confere hash/integridade
e faz backup da versão anterior. **Nunca substitui web-mvc/radar-web.db**,
que armazena usuários e favoritos. Para abrir o site temporariamente com as
vagas baixadas, a partir da raiz do repositório:

~~~powershell
$env:RADAR_DB_PATH = (Resolve-Path .\data\classroom_latest.db).Path
cd web-mvc
mvn spring-boot:run
~~~

Este é um snapshot **separado para a aula**, não uma sincronização incremental
dos dados da interface. Consulte [detalhes e cuidados](web-mvc/README.md).


### Gupy: auditoria de vagas encerradas

A busca pública da Gupy não garante cobertura completa: ausência em uma
busca, HTTP 404, falha de rede ou bloqueio não provam encerramento. O radar
agora desativa anúncios apenas mediante status explicitamente
closed/canceled/closedAt ou aviso inequívoco na página oficial da vaga.

Durante DAILY_AUDIT, até 150 links são verificados por execução (ajustável
por GUPY_AUDIT_LIMIT até 2000). A tabela gupy_url_checks mantém a rotação
dos links; vagas encerradas não são reabertas por resultados antigos.
Os registros são preservados, alterando somente o status ativo.

Para revisar as vagas no banco utilizado na aula, pare o Spring e use
estes comandos na raiz do projeto:

~~~powershell
python -m tools.audit_gupy_lifecycle --db data/classroom_latest.db --limit 500
python -m tools.audit_gupy_lifecycle --db data/classroom_latest.db --limit 500 --apply
~~~

Para atualizar o banco habitual do site, substitua o caminho por
web-mvc/radar-web.db. A opção --apply cria backup SQLite consistente,
sincroniza source_postings e mantém contas/favoritos/candidaturas.
**Sem --apply, apenas mostra uma prévia das detecções.**
Os resultados dependem de páginas públicas acessíveis e de avisos
explícitos; inconclusivas continuam ativas até nova confirmação.


#### Gupy: links novos /job/Base64 e confirmações manuais

Além de /jobs/123, a Gupy usa links /job/Base64, em que o Base64
representa um JSON com jobId e source=gupy_portal.
O verificador reconhece os dois formatos e os alertas em inglês
"Applications closed" / "This position has been paused by the company".

Para testar exatamente uma vaga, não os 500 primeiros anúncios da fila:

~~~powershell
python -m tools.audit_gupy_lifecycle --db web-mvc/radar-web.db --url "https://coplana.gupy.io/job/eyJqb2JJZCI6MTIzMTQwNzcsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0="
~~~

Se a página só revelar o status via JavaScript, o HTML do cliente Python
pode ser inconclusivo. **Depois de confirmar no seu navegador que a vaga
está encerrada**, use esta alternativa explícita:

~~~powershell
python -m tools.audit_gupy_lifecycle --db web-mvc/radar-web.db --confirm-closed-url "https://coplana.gupy.io/job/eyJqb2JJZCI6MTIzMTQwNzcsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=" --apply
~~~

O comando localiza a vaga pelo ID dentro do link e marca como inativas
somente suas publicações Gupy existentes no SQLite indicado, preservando
todos os registros, contas e favoritos. Se o ID não existir no banco,
informa o fato e não modifica nenhuma vaga. Esta confirmação manual não
é usada na coleta automática.

Para diagnosticar divergência entre o SQLite antigo do site e a base da
aula sem fazer consultas externas:

~~~powershell
python -m tools.audit_gupy_lifecycle --db web-mvc/radar-web.db --limit 0
python -m tools.audit_gupy_lifecycle --db data/classroom_latest.db --limit 0
~~~

A saída [ANTES] informa quantos anúncios permanecem no histórico, quantos
estão ativos e quantos são da Gupy. Não misture os dois bancos: o
arquivo do site mantém usuários/favoritos, enquanto o banco baixado do
Actions é uma cópia independente do catálogo.


#### Cobertura de TODAS as fontes (não só as reclamações)

O verificador genérico lê a tabela source_postings e usa as famílias
**gupy_global, gupy_api, gupy_public, 99jobs, vagas_com, ciee, cargill,
ashby, lever, greenhouse, workday, smartrecruiters, inhire, izirh,
eightfold, teamtailor, totvs, successfactors, walljobs, cia_estagios,
nube, iel, superestagios, taqe, bettha, matchbox e cia_talentos**.
Inclui fontes atualmente desabilitadas, pois seus registros históricos
continuam na base. A validação de URLs aplica hosts fixos por plataforma e
hosts corporativos extraídos do cadastro oficial de tenants; links externos
desconhecidos não são acessados e ficam como não verificados.

Inspecione a situação **de todas as fontes existentes no seu SQLite**,
sem redes nem modificações:

~~~powershell
python -m tools.audit_source_availability --db web-mvc/radar-web.db --report
~~~

Para auditar um lote distribuído pelas fontes (prévia primeiro):

~~~powershell
python -m tools.audit_source_availability --db web-mvc/radar-web.db --limit 500
python -m tools.audit_source_availability --db web-mvc/radar-web.db --limit 500 --apply
~~~

O modo --apply faz backup e mantém conta/favoritos. Também salva
inconclusivas separadamente sem fechá-las. Pode ser repetido; a fila
prioriza verificações antigas e percorre todas as fontes (limite máximo
de 1000 por execução). Para a base da aula, use --db data/classroom_latest.db.

Nas coletas com DAILY_AUDIT, um lote de até 80 anúncios entre plataformas
é automaticamente verificado por execução, ajustável pela variável de
ambiente SOURCE_AVAILABILITY_AUDIT_LIMIT (0 a 2000). Nenhuma vaga
não verificada é divulgada como "abertura confirmada".

**Importante:** nem todos os ATS expõem publicamente o formulário e o
estado das inscrições. Uma URL segura mas sem status claro recebe resultado
inconclusivo; não é possível prometer verificação 100% sem credenciais ou
APIs contratadas. A fila aponta também fontes ainda não reconhecidas.

## Login consistente ao atualizar o banco de vagas (recomendado)

A causa de muitos logins que funcionam em um aparelho mas não em outro é
a troca de SQLite pelo RADAR_DB_PATH. **As contas são armazenadas no banco
usado pelo Spring**; rodar sobre data/classroom_latest.db faz o site
enxergar contas diferentes das do antigo web-mvc/radar-web.db.

Para juntar as vagas recentes ao banco que contém suas contas, pare o
Spring Boot e rode na raiz do projeto:

~~~powershell
python -m tools.sync_web_catalog --import-accounts
~~~

O script lê data/classroom_latest.db e atualiza as tabelas do catálogo
dentro de web-mvc/radar-web.db, com backup automático em web-mvc/backups.
Contas e favoritos existentes **não são apagados**. Se a conta foi criada
no banco da aula, --import-accounts traz também seus registros pessoais;
se existirem nomes de usuário iguais representando contas diferentes,
a sincronização é bloqueada para evitar mistura de identidade.
Avisos de encerramento confirmados no SQLite antigo são preservados; as
verificações da base recente são importadas.

Depois SEMPRE inicie o servidor apontando para o banco fixo:

~~~powershell
$env:RADAR_DB_PATH = (Resolve-Path .\web-mvc\radar-web.db).Path
cd web-mvc
mvn spring-boot:run
~~~

Um aviso aparece na página de login caso o servidor esteja apontando para
classroom_latest.db. **Não altere o SQLite do site enquanto ele estiver
aberto pelo Spring.** Para baixar novas vagas no futuro, primeiro use
python tools/pull_classroom_db.py; depois execute o sync acima, parando
o Spring entre as etapas. Não é necessário cadastrar uma conta nova.

### Confirmar encerramento e sinalizar links indisponíveis

Alguns portais continuam exibindo uma descrição após o encerramento,
enquanto outros retornam HTML vazio, 404 ou bloqueio de acesso.
Agora a auditoria permite corrigir anúncios específicos, sem apagar
histórico, usuários, favoritos ou candidaturas.

Use --confirm-closed-url LINK para marcar como encerrada uma candidatura
que foi confirmada; use --flag-unavailable-url LINK para indicar apenas
que não foi possível confirmar a candidatura (por exemplo, 404). Os dois
argumentos são repetíveis, só funcionam com --apply, fazem backup antes
de modificar o banco e não fazem requisições de rede nesse modo.

Exemplo (PowerShell, na raiz do repositório, com Spring Boot parado):

~~~powershell
python -m tools.audit_source_availability --db web-mvc/radar-web.db --confirm-closed-url "https://jobs.zf.com/job/Araraquara-Estágio-Recursos-Humanos-SP-14800-655/1431252033/" --apply

python -m tools.audit_source_availability --db web-mvc/radar-web.db --flag-unavailable-url "https://vagasmaispetoficial.gupy.io/job/eyJqb2JJZCI6MTI0NDQxOTEsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=" --apply
~~~

Links ausentes do SQLite são informados e não modificam registros.
URLs novas da Gupy /job/Base64 são associadas às antigas /jobs/ID pelo
ID comprovado no endereço. A confirmação manual de uma vaga encerrada
não pode ser revertida por uma falha temporária posterior.

O verificador automático também reconhece o texto oficial
"Sorry, this position has been filled" da ZF/SuccessFactors como
encerramento. Um 404, redirecionamento, bloqueio ou login obrigatório
continuam sendo inconclusivos; não se afirma que a vaga foi fechada.
