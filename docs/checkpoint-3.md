# Checkpoint 3 — Incremental integrity

Checkpoint 3 separates **discovery memory** from the active job catalog and adds
a conservative vacancy lifecycle.

## Invariants

1. A source ID can be remembered without becoming a catalog job.
2. Early-stop/probe/partial scans never count as evidence that a vacancy closed.
3. A vacancy becomes `missing` only after a complete scope scan did not return it.
4. A vacancy becomes `inactive` only after two complete misses by default.
5. A previously inactive ID is reactivated when positively observed again.
6. Sources with cheap incremental scans receive a periodic full audit (default:
   every seven successful runs) so old vacancies can eventually be retired.
7. `FULL_DISCOVERY=1` also disables incremental early-stop in additional ATS
   sources.

## New SQLite state

The existing `jobs` table receives:

- `last_checked_at`
- `missing_since`
- `inactive_at`
- `miss_count`
- `seen_count`

Two auxiliary tables are added:

- `discovery_state`: remembers catalog and out-of-scope source IDs.
- `collection_scopes`: remembers partial/full scope scans and schedules periodic
  full audits.

## SuccessFactors

The fast probe may see IDs that are new to the employer catalog but visibly
outside the early-career scope. These IDs are stored in `discovery_state` as
`out_of_scope`, not in `jobs`. On later runs they are known and no longer appear
as repeated `new catalog | 0 new early-career` noise.

Uncertain/untitled IDs are intentionally not marked out-of-scope; they remain
eligible to trigger the targeted collector again.

## Safe reconciliation coverage

Collectors report `complete` only when they can prove the configured scope was
fully traversed. Workday, SmartRecruiters, InHire, IziRH, TOTVS, Teamtailor and
Eightfold participate in lifecycle reconciliation.

A source hitting a safety cap, repeated page, early-stop or other inconclusive
condition reports `partial` and cannot increment `miss_count`.

## Source expansion

Checkpoint 3 adds public tenants discovered/verified in September 2026.

### InHire

V360, Bridge&Co, Cielo, DB1 Group, GX2, Aldak Tecnologia, J.Assy, Dati,
iSystems, Yandeh and ICON IT.

### IziRH

levva, Advice and Grupo Sertec.

Run `python validate_checkpoint3_sources.py` for a live smoke test.

## Daily audit on GitHub Actions

The scheduled GitHub Actions run uses `DAILY_AUDIT=1`.

Daily audit behavior:

- restores `data/opportunity_radar.db` from the newest Actions cache;
- disables listing/query early-stop for the audit;
- preserves known IDs so detail pages can still be reused/skipped;
- runs lifecycle reconciliation only for scopes whose collectors can prove
  complete coverage;
- saves the updated SQLite database to a new cache after a successful run;
- uploads a seven-day SQLite snapshot artifact for manual recovery.

Local `python main.py` remains the fast incremental mode.

`FULL_REFRESH=1` is still different: it also disables known-detail reuse and is
reserved for explicit rebuild/debug scenarios.
