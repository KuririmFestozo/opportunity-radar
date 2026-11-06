# Opportunity Radar — Entrega 2 (MVC Java)

Este módulo adiciona Java 17, Spring Boot 3.4.3, Thymeleaf, Spring Data JPA e
Hibernate SQLiteDialect ao projeto Python existente. Os coletores e o dashboard
Python seguem independentes.

## Funcionalidades demonstráveis

- Catálogo paginado (12 por página) e busca por empresa, título e descrição;
- Filtros por localização, fonte, curso/afinidade e situação ativa/inativa;
- Detalhes, fontes de publicação e pontuações por curso;
- Favoritos persistidos: adicionar, listar e remover (CRUD via JPA);
- Acompanhamento persistido de candidaturas: criar, editar, listar e remover;
- Validação de status e anotações, links externos seguros, layout responsivo;
- Testes Spring MVC/Thymeleaf e persistência JPA em SQLite real.

## Usando uma cópia do SQLite existente

Na raiz do repositório, no PowerShell:

    python web-mvc/tools/prepare_sqlite_snapshot.py data/opportunity_radar.db web-mvc/radar-web.db
    $env:RADAR_DB_PATH = (Resolve-Path web-mvc/radar-web.db).Path
    cd web-mvc
    mvn spring-boot:run

Abra http://localhost:8080.

A cópia é feita usando a API de backup do SQLite (consistente mesmo se a origem usar WAL); o script nunca substitui um arquivo existente. Use um nome novo caso já tenha uma cópia. A cópia deve conter as tabelas relacionais do Checkpoint 4:
opportunities, source_postings e opportunity_course_scores. Se o banco local
ainda não tiver essas tabelas, migre uma **cópia** usando as instruções CP4,
não a base principal. O módulo verifica o arquivo e o esquema durante o
startup, evitando criar um banco acidentalmente vazio.

## Demonstração reproduzível (dados fictícios)

O repositório não inclui o SQLite com dezenas de milhares de registros.
Se precisar demonstrar sem o arquivo original:

    python web-mvc/tools/create_demo_db.py web-mvc/demo.db
    $env:RADAR_DB_PATH = (Resolve-Path web-mvc/demo.db).Path
    cd web-mvc
    mvn spring-boot:run

Os seis registros desse banco são **fictícios**, identificados como exemplos;
não são vagas para candidatura. O script recusa sobrescrever arquivos.

## Executar os testes

    cd web-mvc
    mvn test

Os testes iniciam Spring Boot e SQLite descartável e verificam busca, filtros,
detalhes, URLs, favoritos, candidaturas e validações.

## Arquitetura MVC

- Controller: endpoints, parâmetros e formulários;
- Domain: Opportunity, SourcePosting, CourseScore, Favorite e ApplicationEntry;
- Repository: Spring Data JPA e filtros Specification;
- Service: consulta, validação, classificação e operações persistentes;
- View: páginas HTML Thymeleaf com CSS responsivo;
- Banco: SQLite existente com tabelas adicionais para a camada web.

A aplicação preserva web_favorites e web_applications legadas, cria tabelas
web_device_favorites e web_device_applications para identificação por navegador,
e **índices de consulta**
sobre as tabelas relacionais na **cópia** do SQLite. O índice composto
(opportunity_id, is_active, source) evita uma consulta correlacionada muito
lenta em bancos com dezenas de milhares de registros. O índice de updated_at
acelera a paginação, e o de course_id acelera os filtros.
O script SQL é idempotente; Hibernate DDL está DESLIGADO.
O site não altera registros nem lifecycle das oportunidades coletadas.
Na primeira inicialização, a criação dos índices pode consumir alguns segundos.

## Limitações e segurança

- O site possui autenticação por usuário e senha, mas continua como protótipo
  para testes temporários: recuperação de senha e produção ficam para depois.
- SQLite só aceita uma transação de escrita por vez. Por isso recomendamos uma
  cópia do banco, sem disputar gravações com o processo de coleta.
- A busca textual usa LIKE, não FTS. Para dezenas de milhares de vagas,
  pode ser ampliada posteriormente com índices de pesquisa específicos.
- O backend PostgreSQL permanece como projeto independente; esta entrega não
  converte o banco e não exige Supabase.



## Login, favoritos e dispositivos

Há cadastro, login e logout com Spring Security. Sem Supabase ou códigos.
Crie um usuário (3-40 caracteres) e uma senha forte (10-64 caracteres)
em /register; depois use /login para entrar no computador e no celular.

- Os hashes de senha usam BCrypt (custo 12), nunca texto puro.
- Contas ficam na tabela web_users do SQLite da interface.
- Favoritos e candidaturas usam owner_id vinculado ao UUID da conta,
  isolando completamente usuários diferentes.
- No primeiro login no **mesmo navegador** onde havia listas anônimas, elas
  são migradas para a conta. Dados de outros navegadores não são adivinhados
  e permanecem preservados; não são apagados.
- O túnel Cloudflare muda de domínio, mas as contas continuam no banco:
  use o mesmo usuário e senha na nova URL.
- Favoritos, candidaturas e Minha conta exigem login; catálogo e detalhes
  continuam públicos. POSTs usam CSRF e a sessão é protegida contra fixation.
- A busca mantém localização mediante consentimento, proximidade por
  Haversine, afinidade, raio, filtros por curso/tipo/modalidade, texto e fonte.

O site é um **protótipo de teste**. Ainda não possui validação de e-mail,
recuperação de senha, MFA ou proteção de borda robusta. Mantenha o notebook
ligado e o túnel temporário. A localização arredondada é enviada na URL,
mas não é armazenada no SQLite.

**Preserve radar-web.db** após criar usuários: não sobrescreva o arquivo
com um snapshot novo, pois ele passa a conter suas contas e listas.


## Baixar o banco de vagas mais recente para a aula

O GitHub Actions publica diariamente um snapshot privado do SQLite no
release radar-state-latest. O git pull baixa código, não dados SQLite.

A partir da raiz do repositório, instale o GitHub CLI (uma única vez), caso
não esteja instalado:

~~~powershell
winget install --id GitHub.cli -e
gh auth login
~~~

Depois, sempre que quiser atualizar as vagas para uma demonstração:

~~~powershell
git pull --ff-only origin main
python tools/pull_classroom_db.py
~~~

O comando usa a autenticação do gh para baixar o snapshot main,
confere os SHA-256 do gzip e do banco, valida integridade/tabelas/contagem
e grava em data/classroom_latest.db. Em uma atualização, faz backup do
arquivo anterior em data/backups/. Se o arquivo tiver usuários ou favoritos,
**recusa sobrescrever** (use --output data/classroom_outra_data.db).

Para **demonstrar o Java com a versão baixada** (PowerShell, na raiz):

~~~powershell
$env:RADAR_DB_PATH = (Resolve-Path .\data\classroom_latest.db).Path
cd web-mvc
mvn spring-boot:run
~~~

**Muito importante:** data/classroom_latest.db é um banco separado
**para a aula**. Contas e favoritos existentes em web-mvc/radar-web.db
não são apagados nem aparecem automaticamente nesse outro arquivo.
Se você fizer cadastro/login no snapshot da aula, ele receberá contas
próprias e o próximo pull se recusará a substituí-lo. Pare o Spring antes
de atualizar o arquivo; para manter as contas entre refreshes, será
necessária uma sincronização incremental de catálogo (etapa futura).

Se desejar continuar usando sua conta e favoritos habituais, mantenha
RADAR_DB_PATH apontado para web-mvc/radar-web.db; baixar a base nova
**não altera automaticamente as vagas desse arquivo**.

O arquivo remoto contém dezenas de milhares de vagas e pode ser grande:
o .db.gz principal ocupa aproximadamente 100 MB em 6/11/2026. A API
do GitHub exige permissão de acesso ao repositório privado.

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
