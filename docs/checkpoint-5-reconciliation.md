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
