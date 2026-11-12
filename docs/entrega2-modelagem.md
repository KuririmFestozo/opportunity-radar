# Entrega 2 — modelagem e banco de dados

## Arquitetura implementada

O Opportunity Radar divide responsabilidades entre (1) **pipeline Python**, que coleta, normaliza, classifica, identifica publicações e atualiza o SQLite, e (2) **módulo \`web-mvc/\` em Java Spring Boot**, que expõe catálogo, autenticação, favoritos e candidaturas. Os filtros de busca são aplicados **após** a coleta.

### MVC

- **Controller:** \`OpportunityController\`, \`AuthController\`, \`TrackingController\` e \`ProfileController\` recebem rotas e dados de formulários.
- **Service:** \`AdvancedSearchService\`, \`CatalogService\`, \`AccountService\`, \`TrackingService\` concentram consultas e regras de negócio.
- **Repository:** interfaces Spring Data JPA implementam persistência de \`Opportunity\`, \`SourcePosting\`, \`CourseScore\`, \`Favorite\`, \`ApplicationEntry\` e \`UserAccount\`.
- **Domain:** as classes usam \`@Entity\`, \`@Table\`, \`@Id\` e \`@Column\`, conforme Jakarta Persistence.
- **View:** HTML Thymeleaf em \`web-mvc/src/main/resources/templates/\`, com CSS responsivo.

O projeto usa **Java 17 como versão-alvo**, Spring Boot **3.4.3**, SQLite JDBC e Hibernate Community Dialects. A aula do AVA sobre JPA apresenta conceitos de ORM, mas o banco MySQL e as entidades do tutorial **não** pertencem a esta implementação.

## Entidades e chaves

| Tabela | Chave primária | Papel |
|---|---|---|
| \`opportunities\` | \`id\` | Oportunidade consolidada (título, empresa, descrição, localização) |
| \`source_postings\` | \`(source, source_job_id)\` | Publicação na fonte, URL, \`is_active\`; \`opportunity_id\` referencia a oportunidade |
| \`opportunity_course_scores\` | \`(opportunity_id, course_id)\` | Pontuação de afinidade |
| \`opportunity_intents\` | \`(opportunity_id, intent_id)\` | Categorias/intenções |
| \`source_availability_checks\` | \`(source, source_job_id)\` | Estado \`open\` / \`closed\` / \`unverified\`, evidência e data |
| \`web_users\` | \`id\` | Usuários e hashes BCrypt |
| \`web_device_favorites\` | \`id\` | Favoritos por \`owner_id\` e oportunidade |
| \`web_device_applications\` | \`id\` | Status e anotações pessoais |
| \`web_favorites\`, \`web_applications\` | \`id\` | Tabelas legadas preservadas |

A chave \`(source, source_job_id)\` impede que IDs externos iguais em plataformas diferentes sejam confundidos. As relações pessoais via \`owner_id\` são **vínculos lógicos** às contas, e não devem ser chamadas de FK física onde a declaração SQL não existir.

## Diagrama lógico simplificado

\`\`\`mermaid
flowchart TD
    O[opportunities]
    P[source_postings]
    C[opportunity_course_scores]
    I[opportunity_intents]
    A[source_availability_checks]
    U[web_users]
    F[web_device_favorites]
    X[web_device_applications]

    P -->|opportunity_id| O
    C -->|opportunity_id| O
    I -->|opportunity_id| O
    A -.->|source + source_job_id| P
    F -.->|owner_id| U
    X -.->|owner_id| U
    F -.->|opportunity_id| O
    X -.->|opportunity_id| O
\`\`\`

Linhas pontilhadas representam vinculações lógicas não necessariamente implementadas com restrição de FK.

## Integridade e desempenho

- \`spring.jpa.hibernate.ddl-auto=none\`: evita reconstrução automática de tabelas do coletor;
- \`web-schema.sql\`: cria tabelas web e índices idempotentes;
- \`SQLiteConfig\`: aplica integridade referencial e timeout de conexão;
- índice composto em \`source_postings(opportunity_id, is_active, source)\` para listagem por oportunidade;
- índice em \`opportunities(updated_at DESC)\` para ordenação do catálogo;
- índice de curso/afinidade em \`opportunity_course_scores\`;
- consultas parametrizadas em \`AdvancedSearchService\` e carregamento de entidades por JPA.

## Disponibilidade versus ciclo de vida

\`is_active=1\` indica publicação considerada ativa pela coleta. **Não garante inscrições abertas.** A auditoria mantém estado independente: \`open\` (sinal explícito de abertura), \`closed\` (encerramento comprovado) ou \`unverified\` (sem comprovação). Falhas 404, redirecionamentos, CAPTCHAs e login obrigatório são inconclusivos. Uma vaga encerrada permanece no histórico.

## Execução e teste

Ver [guia de execução local](entrega2-execucao-local.md) e [roteiro de testes](entrega2-roteiro-testes.md). A demonstração deve usar o gerador de **seis vagas fictícias**, não um banco com dados pessoais.
