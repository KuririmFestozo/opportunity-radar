# Execução local — Entrega final (PostgreSQL, Spring MVC e Thymeleaf)

> **Caminho mais simples para avaliar:** execute `docker compose up --build` na raiz do projeto e abra <http://localhost:8080/opportunities>. A demonstração é independente dos snapshots privados do GitHub.

## 1. Requisitos

- Git (para clonar o repositório)
- Docker Desktop com Docker Compose v2 (Windows, Linux ou macOS)
- Portas locais **8080** e **5433** disponíveis

## 2. Clonar e executar do zero

```powershell
git clone https://github.com/KuririmFestozo/opportunity-radar.git
cd opportunity-radar
docker compose up --build
```

O Compose inicia dois serviços:

1. **db**: PostgreSQL 16, banco `opportunity_radar`; cria tabelas e importa seis oportunidades fictícias.
2. **web**: aplicação Java 17/Spring Boot MVC/Thymeleaf; valida o esquema, expõe o site em 127.0.0.1:8080 e conecta via JDBC ao PostgreSQL.

O Docker inicializa os dados automaticamente **na primeira criação do volume** `radar_pgdata`. Nas inicializações seguintes, os dados do PostgreSQL persistem.

Abra:

- <http://localhost:8080/opportunities> — catálogo e filtros
- <http://localhost:8080/register> — criar conta
- <http://localhost:8080/login> — entrar
- <http://localhost:8080/favorites> — favoritos (requer login)
- <http://localhost:8080/applications> — candidaturas (requer login)

Para verificar o banco sem instalar um cliente SQL:

```powershell
docker compose exec db psql -U radar -d opportunity_radar -c "SELECT COUNT(*) FROM opportunities;"
```

O resultado inicial deve ser **6**. Os exemplos estão identificados no nome da empresa como `(exemplo)`.

## 3. Parar, reiniciar e preservar dados

```powershell
docker compose down   # Para os containers, preserva o volume do banco
docker compose up --build
```

**Não execute `docker compose down -v`** se quiser preservar contas, favoritos e candidaturas: `-v` exclui o volume persistente PostgreSQL.

## 4. Rodar Java fora do Docker (opcional)

Requer JDK 17+ e Maven. Inicie somente o PostgreSQL:

```powershell
docker compose up -d db
$env:SPRING_DATASOURCE_URL='jdbc:postgresql://localhost:5433/opportunity_radar'
$env:SPRING_DATASOURCE_USERNAME='radar'
$env:SPRING_DATASOURCE_PASSWORD='radar_demo_local_only'
mvn -f web-mvc/pom.xml spring-boot:run
```

O `application.properties` define defaults locais equivalentes, mas o Compose injeta explicitamente a conexão dentro da rede Docker. O web-app utiliza **PostgreSQL**, não o SQLite dos coletores Python.

## 5. Testes automatizados

```powershell
mvn -f web-mvc/pom.xml test
```

Os testes Java usam **Testcontainers PostgreSQL**: Docker Desktop deve estar em execução. O banco é descartável e isolado; os testes não apagam registros do `db` do Compose nem da sua base pessoal.

A CI de `.github/workflows/ci.yml` roda os testes Java em ambiente com Docker e testes Python separadamente.

## 6. Segurança

- Senhas armazenadas exclusivamente como hashes **BCrypt** (Spring Security).
- Proteção CSRF em formulários autenticados, sessões no servidor e controle de acesso por conta.
- Credenciais no `docker-compose.yml` são **apenas para demonstração local**, não para deploy público.
- O PostgreSQL está exposto somente em `127.0.0.1:5433` e o site somente em `127.0.0.1:8080`.
- Não existe recuperação de senha por e-mail neste protótipo.

## 7. Importação opcional do antigo SQLite para o PostgreSQL

A demonstração funciona **sem executar esta etapa**. Se for necessário continuar usando os registros reais ou as contas antigas, pare o site e mantenha um backup do banco original. O importador não escreve no SQLite.

```powershell
python -m pip install psycopg2-binary
$env:PG_DSN='postgresql://radar:radar_demo_local_only@localhost:5433/opportunity_radar'
python tools/import_sqlite_to_postgres.py --from-db web-mvc/radar-web.db --include-users
```

Antes do importador, inicie o PostgreSQL com `docker compose up -d db`. Se não desejar importar usuários, omita `--include-users`.

A importação copia apenas tabelas necessárias para o web-app, sem reconfigurar a coleta em Python. Ela não elimina o SQLite antigo. Se surgirem conflitos ou erros, a transação PostgreSQL é revertida.

## 8. Arquitetura e arquivos

| Componente | Tecnologia | Localização |
|---|---|---|
| Interface | Thymeleaf / SIGNAL | `web-mvc/src/main/resources/templates` |
| Controle e autenticação | Java/Spring MVC/Spring Security/BCrypt | `web-mvc/src/main/java` |
| Persistência do site | PostgreSQL 16 + JPA/Hibernate e JDBC | `docker-compose.yml` |
| DDL catálogo | SQL PostgreSQL | `web-mvc/src/main/resources/db/catalog-schema.sql` |
| DDL dados pessoais | SQL PostgreSQL | `web-mvc/src/main/resources/db/web-schema.sql` |
| Dados fictícios | SQL | `web-mvc/src/main/resources/db/seed-demo.sql` |
| Coleta separada | Python / SQLite | `collectors/`, `processing/`, `storage/` |

### Solução de problemas

- **Porta 8080 ocupada:** feche o servidor Spring Boot anterior.
- **Porta 5433 ocupada:** pare outra instância PostgreSQL local, ou altere somente o mapeamento de host no Compose e nas configurações locais.
- **Docker daemon indisponível:** inicie o Docker Desktop.
- **Banco não criado:** use `docker compose logs db` e verifique se não há um volume criado anteriormente com outro esquema. Faça backup antes de qualquer reset.
- **Build Maven falhou por rede:** Docker precisa baixar imagens e dependências da primeira vez.
- **Erro de conexão:** `docker compose ps` e `docker compose logs web` para checar os serviços.
