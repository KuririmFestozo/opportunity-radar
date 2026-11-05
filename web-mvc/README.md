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

- Protótipo monousuário, ouvindo por padrão apenas em 127.0.0.1.
  A proteção CSRF está ativa, mas **não há autenticação real**, contas ou
  controle de permissões. Use Cloudflare Quick Tunnel apenas para testes
  temporários e evite colocar dados sensíveis no site.
- SQLite só aceita uma transação de escrita por vez. Por isso recomendamos uma
  cópia do banco, sem disputar gravações com o processo de coleta.
- A busca textual usa LIKE, não FTS. Para dezenas de milhares de vagas,
  pode ser ampliada posteriormente com índices de pesquisa específicos.
- O backend PostgreSQL permanece como projeto independente; esta entrega não
  converte o banco e não exige Supabase.


## Busca avançada e perfis por navegador (Entrega 2+)

A interface agora traz recursos da versão Python anterior:

- **Usar minha localização**: após consentimento do navegador (HTTPS ou
  localhost), arredonda latitude/longitude para **2 casas decimais** e usa
  Haversine para ordenar todas as oportunidades por distância, antes de
  paginar. O cálculo só é possível para vagas com coordenadas. Sem latitude/
  longitude, distância desconhecida aparece por último.
- **Raio máximo** (1 a 1000 km), com opção de incluir anúncios remotos fora
  do raio. A localização **não é salva** no banco; por ser enviada em
  parâmetros de busca, fica visível na URL/histórico e infraestrutura do
  túnel. Use "Limpar filtros" para removê-la da URL.
- **Afinidade**: maior pontuação entre os cursos ou pontuação do curso
  selecionado; filtros por pontuação mínima, tipo, modalidade, fonte,
  palavras obrigatórias/excluídas e local.
- **Ordenação**: maior afinidade, mais perto, mais recente e título A–Z.
  A ordenação não se limita às 12 vagas visíveis: ocorre antes da paginação.
  Não há coleta ao vivo por localização nesta interface; as buscas usam as
  oportunidades já presentes no snapshot do SQLite.
- **Favoritos e candidaturas diferentes por navegador**: o backend emite
  cookie aleatório de 256 bits, HttpOnly, SameSite=Lax e Secure no túnel
  HTTPS. O SQLite tem tabelas web_device_favorites e web_device_applications
  com chave composta (owner_id, opportunity_id); dados são persistidos,
  porém isolados entre perfis.
- **Código de recuperação** em "Meu perfil": serve para restaurar as listas
  quando mudar a URL temporária da Cloudflare ou usar as mesmas listas em
  outro aparelho. **É um segredo equivalente a senha:** quem tiver o código
  acessa suas listas/anotações. Se quiser listas diferentes, não compartilhe
  o código. É possível criar outro perfil sem apagar o anterior.
- **CSRF em todos os POSTs** usando Spring Security, sem exigir login.
  O protótipo continua local e monousuário. Não o exponha indefinidamente
  nem utilize para dados confidenciais sem autenticação real.

**Compatibilidade:** as duas antigas tabelas globais web_favorites e
web_applications são preservadas intactas (sem dono inferível) e não
aparecem automaticamente nas novas listas isoladas. Nenhuma oportunidade
é modificada. Uma nova URL trycloudflare.com cria um novo cookie: use
"Meu perfil" para restaurar o perfil anterior.

**Limitações:** presets com múltiplos cursos, filtro de país com metadados
estruturados, e a busca dinâmica externa do antigo dashboard ainda não
estão implementados na camada Java. A entrega cobre os recursos principais
de busca local, distância, afinidade e acompanhamento.
