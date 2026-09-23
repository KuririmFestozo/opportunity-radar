# Roadmap — Opportunity Radar

Este documento registra a evolução arquitetural do projeto.

O README descreve o produto no estado atual; este arquivo mantém a sequência dos checkpoints.

---

## Visão geral

```text
CP1   Consistência
CP2   Identidade + deduplicação
CP2.x Expansão de fontes e performance
CP3   Integridade incremental
CP3.1 Engenharias + fontes brasileiras
CP4   Persistência unificada
CP5   PostgreSQL / Supabase / PostGIS
CP6   API de catálogo
CP7   Usuários e perfis
CP8   Favoritos e candidaturas
CP9   Web UX definitiva
CP10  Mobile / Expo
```

---

## CP1 — Consistência do pipeline ✅

Objetivo:

- tornar classificação, matching, localização e exports reproduzíveis;
- eliminar inconsistências entre backend e dashboard;
- consolidar testes de regressão.

Resultado:

- pipeline determinístico;
- presets consistentes;
- validação automatizada.

---

## CP2 — Identidade e deduplicação ✅

Objetivo:

- definir identidade por `(source, source_job_id)`;
- separar deduplicação de persistência da deduplicação de catálogo;
- preservar referências de múltiplas fontes;
- evitar merges agressivos.

Resultado:

- identidade source-native preservada;
- cross-source dedup conservador;
- tracking removido sem destruir parâmetros de identidade;
- referências de origem preservadas.

---

## CP2.x — Expansão de fontes e performance ✅

Incluiu:

- SuccessFactors;
- Workday;
- SmartRecruiters;
- InHire;
- IziRH;
- Eightfold;
- TOTVS;
- Teamtailor;
- 99jobs ampliado;
- descoberta dedicada summer/férias;
- fontes brasileiras de estágio;
- regional search;
- early-stop e reutilização incremental.

Subcheckpoints documentados:

- `checkpoint-2.7.md`
- `checkpoint-2.9.md`
- `checkpoint-2x-finalization.md`

---

## CP3 — Integridade incremental ✅

Objetivo:

- diferenciar ausência real de ausência causada por coleta parcial;
- manter memória de IDs descobertos;
- controlar lifecycle sem falsos encerramentos.

Resultado:

```text
active → missing → inactive
          ↑           |
          └───────────┘
            reappear
```

Regras:

- somente scans completos podem incrementar `miss_count`;
- duas ausências completas consecutivas inativam por padrão;
- reaparecimento reativa;
- discovery state pode guardar IDs fora do catálogo;
- auditorias completas periódicas evitam vagas eternamente ativas.

O GitHub Actions passou a manter o SQLite entre execuções.

---

## CP3.1 — Engenharias e fontes brasileiras ✅

Expansão de afinidade para:

- Engenharia Química;
- Engenharia de Materiais;
- Engenharia de Computação;
- Engenharia Física;
- Engenharia Agronômica;
- Engenharia Ambiental;
- Engenharia de Alimentos;
- Engenharia Florestal.

Novas fontes e boards incluíram:

- TAQE;
- Bettha;
- Matchbox;
- Super Estágios;
- Cargill University/Campus;
- Dow;
- Air Liquide;
- Johnson & Johnson;
- Baker Hughes;
- Syngenta;
- SGS;
- Wabtec.

Também foi criado o modo pesado de auditoria no GitHub:

```text
DAILY_AUDIT=1
UNBOUNDED_COLLECTION=1
```

---

# CP4 — Persistência unificada 🚧

Objetivo:

transformar a persistência atual em um modelo relacional claro, sem migrar ainda para PostgreSQL.

Principais mudanças planejadas:

- `opportunity` deixa de ser sinônimo de anúncio de origem;
- anúncios source-native passam a existir como entidades próprias;
- lifecycle fica associado ao anúncio de origem;
- cross-source association passa a ser persistida;
- intents e course scores deixam de depender apenas do JSON serializado;
- exports e dashboard continuam compatíveis.

Documento de escopo:

- `checkpoint-4.md`

---

## CP5 — PostgreSQL / Supabase / PostGIS ⏳

Objetivo:

migrar o modelo estabilizado no CP4 para PostgreSQL.

Inclui:

- Supabase;
- PostGIS;
- índices geográficos;
- migrations;
- execução remota;
- eliminação gradual da dependência de SQLite local.

A intenção é que CP5 seja uma troca de backend, não uma nova reformulação do modelo.

---

## CP6 — API de catálogo ⏳

Objetivo:

expor o catálogo persistente por uma API estável.

Inclui:

- paginação;
- filtros;
- busca textual;
- proximidade;
- course affinity;
- intents;
- source references;
- lifecycle.

---

## CP7 — Usuários e perfis ⏳

Objetivo:

retirar a dependência de perfis estáticos em `config/profiles.py`.

Inclui:

- autenticação;
- perfis persistentes;
- preferências;
- localização;
- curso;
- raio;
- score mínimo.

---

## CP8 — Favoritos e candidaturas ⏳

Objetivo:

transformar descoberta em acompanhamento.

Inclui:

- vagas salvas;
- status da candidatura;
- datas;
- observações;
- histórico.

---

## CP9 — Experiência web definitiva ⏳

Objetivo:

substituir o dashboard gerado por uma interface web orientada a produto.

Inclui:

- catálogo;
- filtros;
- perfis;
- detalhes;
- favoritos;
- candidaturas;
- histórico.

---

## CP10 — Mobile / Expo ⏳

Objetivo:

disponibilizar a experiência em aplicativo.

A API e persistência dos checkpoints anteriores devem permitir que o mobile seja apenas mais um cliente do sistema.
