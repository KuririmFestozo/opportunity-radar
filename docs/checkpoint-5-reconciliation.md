# CP5 — Plano de reconciliação somente leitura

A referência de 10/10/2026 possui 42.132 source postings no SQLite,
contra 33.062 no PostgreSQL: 28.627 compartilhados, 13.505 exclusivos do
SQLite e 4.435 exclusivos do PostgreSQL. A união de 46.567 conta
**identidades de origem**, não vagas únicas/ativas.

## Executar

```powershell
python -m tools.plan_postgres_reconciliation --db data/snapshots/main-20261010.db --output data/snapshots/cp5-reconciliation.json
```

Requer `DATABASE_URL` apenas no ambiente. O comando abre o SQLite em
modo somente leitura, utiliza transação PostgreSQL `REPEATABLE READ` /
`READ ONLY` e finaliza com rollback. O arquivo JSON é relatório local,
não alteração de banco. Não existe `--apply`.

## Política conservadora

- Preservar todos os IDs exclusivos do PostgreSQL.
- Tratar IDs exclusivos do SQLite como candidatos à inserção. Verificar
  colisões de `opportunity_id` antes de qualquer aplicação.
- Separar diferenças de hash, processing_version, associação, lifecycle,
  scores, intents e payloads. Timestamps são evidência, não desempate
  automático.
- Para scores, comparar cada lado com os seus payloads normalizados,
  usando o máximo por curso quando há múltiplos postings associados.
- Não inferir fechamento somente da ausência num snapshot: conferir
  cobertura e saúde dos escopos da coleta.
- O planejador não compara todo campo visível do catálogo: usar em
  conjunto com `tools.diagnose_backend_overlap`.

## Antes de gravar

Exigir backup verificável, plano congelado com contagens/identidades,
implementação transacional separada, rollback testado, validação de
associações e classificações, e revisão de lifecycle por escopo. Não
migrar o workflow diário nem trocar o backend padrão nesta etapa.

## Diagnóstico de proveniência da classificação e cobertura

A partir do plano estendido, inspecione:

- `classification_provenance.metrics`: separação *exclusiva* das
  diferenças de pontuação por oportunidade entre chaves de cursos que faltam
  em um dos bancos, valores divergentes de cursos compartilhados e casos
  mistos. As contagens de células não são contagens de oportunidades.
- `classification_provenance.course_count_distribution`: quantas
  oportunidades compartilhadas possuem 7, 15 ou outra quantidade de cursos
  em cada snapshot.
- `classification_provenance.courses_missing_from_postgres`:
  contagem por `course_id` ausente da tabela relacional do PostgreSQL,
  mas presente no SQLite. Também existe o campo simétrico.
- `classification_provenance.metrics.both_relational_match_own_payload`:
  ambos os catálogos estão consistentes com seus próprios payloads, mas
  podem ter sido classificados em versões ou abrangências diferentes.
- `collection_scope_evidence`: comparação dos registros persistidos de
  `collection_scopes` em ambas as bases. Um escopo marcado como completo
  não prova por si só que cada posting foi coberto; verificar a semântica
  de `scope_key` e o êxito da coleta correspondente.

Em 10/10/2026, uma consulta somente leitura no PostgreSQL identificou
os 7 cursos históricos presentes em 33.062 oportunidades; os 8 cursos
adicionados depois apareciam em apenas 10.325. Logo, 22.737 oportunidades
não tinham aqueles 8 cursos na classificação relacional. Isso justifica
separar expansão do catálogo de inconsistência de pontuação, mas **não**
autoriza recalcular nem gravar sem revisão.

A rotina continua sem opção de escrita e preserva o snapshot analisado.
Uma atualização do GitHub Actions não muda retroativamente os dados do
relatório, mas é preciso regenerar o plano para utilizar novos snapshots.

## CP5 — Estágio transacional aditivo (sem cutover)

`tools/stage_postgres_additions.py` prepara o primeiro estágio, **não a reconciliação completa**.
A prévia não modifica o PostgreSQL ou o SQLite:

```powershell
python -m tools.stage_postgres_additions --db data/snapshots/main-20261010.db --output data/snapshots/cp5-additive-preview.json
```

Uma inserção é candidata somente se `(source, source_job_id)` não existir no
PostgreSQL, o `opportunity_id` também não existir no destino, a oportunidade
possuir um único posting no SQLite e `association_method` ser `identity`.

Grupos cross-source, associações não-identidade e colisões de UUID são
bloqueados e relatados. Não são apagados nem modificados. O estágio copia
apenas oportunidades novas, seus postings, scores, intents e discovery_state.
Preserva todo registro PostgreSQL existente. Não altera lifecycle
compartilhado, não recalcula classificações e não modifica collection_scopes.

### Regras de segurança para futura execução

**Não executar `--apply` nesta fase** sem revisão dos contadores e
ensaio independente de restauração do backup.

A aplicação futura exige `--apply --confirm-additive-only`, SHA-256 imutável
do SQLite (`--expected-source-sha256`), fingerprint do PostgreSQL
(`--expected-postgres-fingerprint`), contagem exata de candidatos
(`--expected-inserts`) e `pg_dump`/`pg_restore` compatíveis com o servidor.

O utilitário cria `pg_dump` do schema public, valida a listagem do dump
e calcula SHA-256. Só então abre transação SERIALIZABLE, bloqueia as
tabelas afetadas, recalcula os guards, insere candidatos, valida contagens
e confirma COMMIT. Falhas antes do commit provocam ROLLBACK.

**Limitação:** validar o sumário de `pg_restore --list` não substitui
um teste de restauração. O código não oferece restauração automática.
Antes da primeira execução real, restaurar o backup em banco isolado e
documentar como recuperar o banco remoto em caso de problema pós-commit.

A segunda etapa (conteúdo compartilhado, lifecycle, classificações antigas
e cobertura por escopo) exige uma rotina separada, ainda não implementada.
Não migrar GitHub Actions nem mudar o backend padrão nesta etapa.
