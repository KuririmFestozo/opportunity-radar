# Post-baseline findings

The exhaustive baseline exposed two important behaviors.

## HTML SuccessFactors queries are not automatically authoritative

CSB JSON searches use a structured `keywords` request and remain trusted as
query-scoped discovery.

Older RMK HTML `/search/?q=...` results are not trusted by default. Some tenants
can ignore the query or return a very broad catalog. Those results therefore
still need visible early-career title/type evidence unless a tenant explicitly
sets `targeted_trust_html_query = True`.

## FULL_DISCOVERY is global

`FULL_DISCOVERY=1` now disables known-page early-stop for SuccessFactors,
Gupy Global and 99jobs.

## Limit diagnostics

SuccessFactors reports job and page guard rails independently.
