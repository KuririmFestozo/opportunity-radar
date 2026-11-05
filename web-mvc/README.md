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

A aplicação cria apenas web_favorites e web_applications com script SQL
idempotente. Hibernate DDL está DESLIGADO para proteger as tabelas Python.
O site não altera dados nem lifecycle das oportunidades coletadas.

## Limitações e segurança

- Protótipo monousuário, ouvindo por padrão apenas em 127.0.0.1. Não publicar
  na internet sem autenticação, autorização, CSRF e configuração adequada.
- SQLite só aceita uma transação de escrita por vez. Por isso recomendamos uma
  cópia do banco, sem disputar gravações com o processo de coleta.
- A busca textual usa LIKE, não FTS. Para dezenas de milhares de vagas,
  pode ser ampliada posteriormente com índices de pesquisa específicos.
- O backend PostgreSQL permanece como projeto independente; esta entrega não
  converte o banco e não exige Supabase.
