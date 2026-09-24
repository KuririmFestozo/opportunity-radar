# Checkpoint 4 — Persistência unificada

## Objetivo

O Checkpoint 4 reorganiza a persistência do Opportunity Radar antes da migração para PostgreSQL/Supabase.

A meta não é trocar de banco ainda.

A meta é garantir que exista **um modelo persistente coerente e estável** para que o Checkpoint 5 seja essencialmente uma mudança de backend.

---


## Progresso de implementação

### Fechamento do CP4 ✅

O CP4 foi considerado concluído após a auditoria completa do GitHub Actions #15 terminar com sucesso, incluindo testes, full audit, checkpoint do SQLite, publicação do estado rolling e upload do dashboard. O catálogo relacional e o bundle de estado do servidor ficaram validados para a transição ao CP5.


### CP4-E.1 — Server state sync ✅

O servidor passa a poder reconstruir seu runtime a partir de um snapshot SQLite
publicado automaticamente pelo GitHub Actions.

Fluxo:

```text
git pull --ff-only
        ↓
download snapshot branch-scoped
        ↓
SHA-256 + PRAGMA integrity_check
        ↓
backup + atomic replace
        ↓
install prebuilt output bundle
        ↓
server.py
```

Componentes:

- `tools/sync_server_state.py` baixa o snapshot rolling da branch atual;
- assets são publicados na release `radar-state-latest`;
- cada branch usa assets próprios para evitar misturar schemas durante desenvolvimento;
- o SQLite só substitui o banco local após checksum e `integrity_check`;
- o banco anterior é preservado em `data/backups/`;
- o workflow empacota `output/` já gerado, evitando rebuild pesado no startup;
- `start_server.ps1` orquestra pull, sync do banco/dashboard e servidor;
- `start_server.ps1 -Offline` usa conscientemente o estado local existente.

O `output/` continua derivado e não é versionado. O SQLite é o estado distribuído.

> Segurança futura: este mecanismo pressupõe que o banco publicado contém apenas
> catálogo público. Antes de armazenar dados pessoais/usuários no mesmo banco,
> o snapshot público deve ser substituído por armazenamento privado/autenticado.




### CP4-E — Relational catalog reads ✅

- o catálogo final passa a ser lido diretamente de `opportunities`;
- `main.py` deixa de montar o catálogo com `load_postings() + deduplicate_jobs()`;
- `source_postings` continua responsável por identidade nativa e lifecycle;
- cada opportunity é projetada como um `Job` compatível para matching/export;
- `source_references` preserva todas as publicações originais;
- a atividade da opportunity é derivada da existência de pelo menos um posting ativo;
- dashboard, JSON, CSV e matching continuam recebendo a mesma interface `Job`.

Com isso, `opportunities` torna-se a entidade de leitura do catálogo. O `jobs`
legado ainda permanece como write-store temporário até o cleanup do CP4-F.



### CP4-D — Relational classification ✅

- `opportunity_course_scores` e `opportunity_intents` passam a ser a fonte de
  verdade para leitura de classificação;
- scores/intents dentro de `job_json` permanecem apenas como snapshot de
  compatibilidade;
- `SQLiteOpportunityRepository.load_postings()` hidrata classificação a partir
  das tabelas relacionais;
- postings ligados à mesma opportunity recebem a mesma classificação consolidada;
- o repository expõe `opportunity_id` e `classification_source=relational`;
- `unified_classification_version=1` registra o contrato no banco.

A classificação ainda é calculada em objetos `Job` no processamento. Esta fase
muda a autoridade de persistência/leitura, não o algoritmo de classificação.



### CP4-C — Persistent associations ✅

- a deduplicação conservadora do catálogo agora expõe os grupos antes do merge;
- esses mesmos grupos são persistidos como `opportunities`;
- múltiplos `source_postings` podem apontar para a mesma opportunity;
- o posting mais antigo funciona como âncora para manter o ID estável;
- associações podem ser desfeitas caso os dados deixem de ser compatíveis;
- course scores usam o maior score observado entre postings associados;
- intents são unificadas entre as fontes;
- a opportunity permanece ativa enquanto qualquer posting associado estiver ativo;
- nenhum source posting é apagado durante merge ou split.

O pipeline ainda escreve primeiro no armazenamento legado. A leitura definitiva
diretamente de `opportunities` fica para o CP4-E.


### CP4-A — Schema + migration ✅

Implementado como **shadow schema**:

- `jobs` continua sendo a fonte de verdade temporária;
- `opportunities` recebe uma opportunity determinística por posting;
- `source_postings` preserva identidade e lifecycle source-native;
- `opportunity_course_scores` recebe a classificação relacional;
- `opportunity_intents` recebe intents relacionais;
- nenhum merge cross-source acontece durante a migration;
- `discovery_state` e `collection_scopes` permanecem intactos;
- o shadow schema é sincronizado após um batch bem-sucedido;
- `tools/migrate_unified_schema.py` permite migrar/validar o banco sem coletar vagas.

Comando de validação:

```powershell
python tools/migrate_unified_schema.py
```

O pipeline ainda lê `jobs`. A troca de leitura/escrita para a nova camada de
repositório pertence aos próximos subcheckpoints.

---

## Problema atual

Hoje o SQLite funciona bem como cache incremental, mas mistura diferentes conceitos.

A tabela `jobs` representa ao mesmo tempo:

- um anúncio de uma fonte;
- uma oportunidade exibida;
- dados normalizados;
- classificação;
- lifecycle;
- payload serializado em `job_json`.

Além disso:

- deduplicação cross-source acontece principalmente em memória;
- `metadata.source_references` guarda associações que deveriam ser entidades persistentes;
- lifecycle é source-specific, mas a futura tabela `opportunities` representa uma vaga consolidada;
- course scores e intents vivem dentro do JSON do `Job`;
- `database/schema.sql` já aponta para PostgreSQL, mas ainda não representa completamente o modelo que o pipeline realmente precisa.

Migrar diretamente esse estado para Supabase faria o projeto carregar ambiguidades atuais para a arquitetura definitiva.

---

## Princípio central

O modelo do CP4 separa:

```text
Opportunity
    ↑
    |
Source Posting
```

### Source Posting

Representa **um anúncio específico em uma fonte**.

Sua identidade continua sendo:

```text
(source, source_job_id)
```

É aqui que ficam:

- URL;
- payload original/normalizado;
- first seen;
- last seen;
- last checked;
- raw hash;
- processing version;
- lifecycle;
- miss count;
- inactive timestamp.

### Opportunity

Representa **a oportunidade consolidada exibida ao usuário**.

Uma opportunity pode estar ligada a:

```text
1 ou mais source postings
```

A associação cross-source deve permanecer conservadora.

---

## Invariantes

1. `(source, source_job_id)` continua sendo a identidade source-native.
2. Nenhum anúncio é hard-deleted durante o lifecycle normal.
3. `missing` e `inactive` pertencem ao source posting.
4. Uma opportunity continua ativa enquanto houver pelo menos um posting ativo associado.
5. Cross-source merge deve ser conservador e reversível.
6. Uma associação errada deve poder ser corrigida sem perder o anúncio original.
7. Dados específicos da fonte nunca são destruídos pelo processo de consolidação.
8. Uma migração do schema antigo deve ser idempotente.
9. A execução não pode exigir PostgreSQL/Supabase no CP4.
10. Os exports atuais devem continuar funcionando durante a transição.

---

## Schema alvo em SQLite

O desenho exato pode evoluir durante a implementação, mas o modelo inicial é:

### `opportunities`

```text
id
company
title
description
location_text
latitude
longitude
location_confidence
workplace_type
employment_type
salary
published_at
canonical_url
created_at
updated_at
```

Não contém lifecycle source-specific.

---

### `source_postings`

```text
source
source_job_id
opportunity_id

url
source_type
normalized_job_json
raw_hash
processing_version

first_seen_at
last_seen_at
last_checked_at
last_changed_at

is_active
missing_since
inactive_at
miss_count
seen_count
```

Chave:

```text
PRIMARY KEY (source, source_job_id)
```

---

### `opportunity_course_scores`

```text
opportunity_id
course_id
score
```

Chave:

```text
PRIMARY KEY (opportunity_id, course_id)
```

---

### `opportunity_intents`

```text
opportunity_id
intent_id
```

Chave:

```text
PRIMARY KEY (opportunity_id, intent_id)
```

---

### `discovery_state`

Mantida do CP3.

Continua permitindo lembrar IDs que:

- foram vistos no catálogo;
- estão fora do escopo;
- ainda são incertos;
- não precisam virar postings imediatamente.

---

### `collection_scopes`

Mantida do CP3.

Continua registrando:

- successful runs;
- last full run;
- coverage;
- timestamps de auditoria.

---

## Associação cross-source

O CP4 não deve criar merges agressivos.

A associação de postings em uma opportunity pode usar a lógica conservadora atual:

- URL de detalhe compatível;
- empresa equivalente;
- título equivalente;
- ausência de conflito forte;
- identificadores explícitos preservados.

Quando a evidência não for suficiente:

```text
criar opportunities separadas
```

Isso é preferível a ocultar uma oportunidade legítima.

---

## Lifecycle

Lifecycle é calculado por posting.

Exemplo:

```text
Opportunity A
├── posting Gupy      active
└── posting Workday   inactive
```

A opportunity continua ativa.

Somente quando todos os postings conhecidos estiverem inativos:

```text
Opportunity A → inactive
```

Na primeira versão do CP4, o estado da opportunity pode ser derivado em consulta em vez de armazenado duplicadamente.

---

## Migração do banco atual

A migração deve:

1. detectar schema antigo;
2. criar as novas tabelas;
3. migrar todos os rows de `jobs`;
4. criar inicialmente uma opportunity para cada posting;
5. aplicar associação conservadora posteriormente;
6. migrar course scores;
7. migrar intents;
8. preservar todos os timestamps e lifecycle do CP3;
9. preservar `discovery_state`;
10. preservar `collection_scopes`;
11. registrar schema version;
12. ser segura para executar novamente.

Nenhuma migração deve depender do arquivo `output/jobs.json`.

O SQLite é a fonte de verdade.

---

## Camada de repositório

O pipeline não deve espalhar SQL novo pelo projeto.

Criar uma abstração, por exemplo:

```text
storage/
├── repository.py
├── sqlite_repository.py
├── migrations/
└── ...
```

Interface conceitual:

```python
class OpportunityRepository:
    def prepare_posting(...)
    def upsert_posting(...)
    def mark_seen(...)
    def reconcile_scope(...)
    def associate_postings(...)
    def load_opportunities(...)
    def load_postings(...)
    def stats(...)
```

O nome final pode mudar.

O importante é que collectors, classification e API não dependam diretamente de detalhes do SQLite.

Isso prepara o CP5 para adicionar:

```text
PostgresRepository
```

sem reconstruir o pipeline.

---

## Etapas concluídas

### CP4-A — Schema e migration

- definir schema v4;
- criar migration idempotente;
- backfill do banco atual;
- testes de preservação de dados.

### CP4-B — Repository abstraction

- introduzir interface;
- encapsular SQLite;
- manter compatibilidade com o `JobStore` durante a transição.

### CP4-C — Persistência de postings e opportunities

- source postings;
- opportunities;
- associação persistente;
- lifecycle por posting.

### CP4-D — Classificação relacional

Persistir:

- course scores;
- intents.

Eliminar dependência desses campos dentro de `job_json` como fonte primária.

### CP4-E — Leitura unificada

Migrar:

- exports;
- dashboard;
- API;
- stats.

Todos passam a ler opportunities consolidadas do repository.

### CP4-F — Compatibilidade e cleanup ✅

- exports atuais preservados;
- suíte de regressão mantida;
- logs de execução tornados explícitos para diferenciar incremental de auditoria completa;
- server state rolling validado de ponta a ponta no GitHub Actions;
- documentação atualizada para encerrar o CP4 e apontar o CP5 como próxima etapa;
- `database/schema.sql` alinhado ao modelo relacional estabilizado.

---

## Critérios de aceite

O CP4 termina quando:

- [x] todos os anúncios existentes migram sem perda;
- [x] source identity continua intacta;
- [x] lifecycle continua conservador;
- [x] cross-source associations persistem entre execuções;
- [x] course scores persistem relacionalmente;
- [x] intents persistem relacionalmente;
- [x] API/dashboard recebem o mesmo catálogo ou um catálogo comprovadamente equivalente;
- [x] exports atuais continuam sendo gerados;
- [x] execução local continua em SQLite;
- [x] GitHub Actions continua persistindo estado entre runs;
- [x] suite de regressão permanece verde;
- [x] não há dependência obrigatória de Supabase.

---

## Fora de escopo

Não fazem parte do Checkpoint 4:

- autenticação;
- usuários;
- favoritos;
- candidaturas;
- UI nova;
- aplicativo mobile;
- migração definitiva para PostgreSQL;
- PostGIS;
- recomendação por ML;
- expansão agressiva de novas fontes.

Esses itens permanecem nos checkpoints posteriores.

---

## Relação com o Checkpoint 5

O CP4 deve produzir um modelo suficientemente estável para permitir:

```text
SQLiteRepository
        ↓
mesma interface
        ↓
PostgresRepository
```

O Checkpoint 5 então cuida de:

- PostgreSQL;
- Supabase;
- PostGIS;
- migrations remotas;
- índices;
- deployment;
- operação persistente em nuvem.

Sem redefinir novamente o significado de opportunity, posting ou lifecycle.
