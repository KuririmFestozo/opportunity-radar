# Checkpoint 5 — PostgreSQL / Supabase / PostGIS

## Objetivo

Migrar o modelo relacional estabilizado no CP4 para PostgreSQL sem redefinir o
domínio do Opportunity Radar.

O CP5 preserva:

- identidade source-native por `(source, source_job_id)`;
- lifecycle por source posting;
- associação cross-source conservadora e reversível;
- classificação relacional por opportunity;
- catálogo lido a partir de `opportunities`;
- `discovery_state` e `collection_scopes`.

---

## Estratégia

A troca de backend será gradual:

```text
SQLite CP4
   ↓
migração idempotente
   ↓
PostgreSQL + PostGIS
   ↓
validação de paridade
   ↓
dual-run controlado
   ↓
PostgreSQL como backend principal
```

SQLite permanece como fallback até a paridade ser comprovada.

Autenticação, usuários, favoritos e candidaturas continuam fora do CP5 e
pertencem aos CP7/CP8.

---

## CP5-A — Schema remoto e bootstrap 🚧

Escopo:

- schema PostgreSQL alinhado ao CP4;
- PostGIS em schema dedicado `extensions`;
- índice GiST para localização;
- driver Psycopg 3;
- repository PostgreSQL de leitura do catálogo;
- ferramenta SQLite → PostgreSQL;
- validação de contagens e identidades;
- conexão por `DATABASE_URL`, sem credenciais versionadas.

Arquivos:

```text
database/schema.sql
database/migrations/0001_cp5_catalog.sql
storage/postgres_repository.py
tools/migrate_sqlite_to_postgres.py
```

### Conexão

A aplicação usa:

```text
DATABASE_URL
```

A connection string real deve vir do ambiente e nunca ser commitada.

Para Supabase, a string deve ser copiada do painel `Connect`. Uma conexão
direta é adequada a backends persistentes quando a rede possui conectividade
compatível; em ambientes IPv4-only pode ser usado o session pooler.

### PostGIS

O modelo usa:

```text
extensions.geography(Point, 4326)
```

PostGIS fica fora de `public` para não expor suas tabelas internas pela Data
API.

### Migração

Inspecionar o SQLite sem acessar PostgreSQL:

```powershell
python -m tools.migrate_sqlite_to_postgres --dry-run
```

Migrar para o banco remoto:

```powershell
$env:DATABASE_URL="<connection string>"
python -m tools.migrate_sqlite_to_postgres
```

Para um bootstrap limpo de um banco dedicado ao catálogo:

```powershell
python -m tools.migrate_sqlite_to_postgres --reset-target
```

`--reset-target` apaga os dados atuais das tabelas do catálogo no destino e
deve ser usado apenas conscientemente.

---

## CP5-B — Paridade de leitura

- comparar SQLite e PostgreSQL;
- validar catálogo, source references, scores e intents;
- validar consultas de proximidade via PostGIS;
- adicionar testes de contrato entre backends.

## CP5-C — Escrita e lifecycle

- portar prepare/upsert/touch;
- portar discovery state;
- portar reconciliation;
- portar collection scopes;
- eliminar o write-through legado.

## CP5-D — Associações cross-source

- persistir merges/splits diretamente no PostgreSQL;
- garantir IDs estáveis;
- validar reversibilidade.

## CP5-E — Operação remota

- GitHub Actions escreve no PostgreSQL;
- secrets ficam apenas no ambiente de execução;
- SQLite deixa de ser o estado distribuído principal;
- snapshot SQLite permanece como fallback temporário.

## CP5-F — Cutover

- PostgreSQL vira o backend padrão;
- paridade final;
- rollback documentado;
- remoção da dependência operacional do SQLite.

---

## Critérios de aceite

- [ ] schema PostgreSQL reproduzível;
- [ ] PostGIS habilitado fora de `public`;
- [ ] todos os source postings migram sem perda;
- [ ] opportunities preservam IDs e associações;
- [ ] course scores e intents têm paridade;
- [ ] discovery state e collection scopes têm paridade;
- [ ] leitura do catálogo é equivalente ao SQLite;
- [ ] lifecycle permanece conservador;
- [ ] GitHub Actions pode operar contra PostgreSQL;
- [ ] nenhuma credencial é versionada;
- [ ] PostgreSQL pode ser usado como backend principal;
- [ ] rollback está documentado.

---

## Segurança

Durante o CP5 o banco remoto contém somente o catálogo público.

As tabelas são criadas com RLS habilitado e sem políticas anônimas. O backend
usa conexão PostgreSQL direta. Políticas para usuários finais serão definidas
somente quando os dados pessoais entrarem no escopo dos CP7/CP8.
