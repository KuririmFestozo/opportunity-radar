# Daily Audit — desativação e remoção segura de anúncios inexistentes

Esta alteração funciona sobre as **27 famílias de fontes** do Opportunity Radar e mantém o SQLite como fonte de verdade. O objetivo é retirar vagas claramente indisponíveis da busca e, apenas após evidência repetida, remover registros que não existem mais.

## Política

| Evidência | Na primeira verificação | Após 3 verificações em dias distintos | Após 5 verificações e pelo menos 14 dias |
|---|---|---|---|
| Mensagem explícita de encerramento / prazo vencido | Desativa imediatamente | Continua desativada | Pode excluir o anúncio e a oportunidade órfã |
| HTTP **404/410** em URL oficial de vaga | Registra como inconclusiva | Desativa | Pode excluir |
| HTTP 403/429, timeout, erro de rede, login, captcha, redirecionamento ou página genérica | Inconclusiva | **Não** desativa | **Não** exclui |

Cada aviso ou HTTP 404/410 representa **no máximo uma verificação por dia UTC**. Um resultado sem evidência concreta interrompe a sequência de confirmações de desaparecimento. Se a página comprovar novamente **inscrições abertas**, uma desativação feita apenas por 404/410 é revertida (nunca uma vaga encerrada explicitamente). URLs antigas da Gupy com `/jobs/123` retornando 404 **não contam**, porque a plataforma mudou o formato para `/job/<token>`.

As verificações de acompanhamento são limitadas por dia. Com milhares de vagas, atingir cinco verificações pode levar bem mais de 14 dias. Os limites são configuráveis:

- `RETIREMENT_RECHECK_LIMIT` (padrão **120**) — máximo de links em rechecagem a cada Daily Audit;
- `RETIREMENT_DELETE_LIMIT` (padrão **30**) — máximo de candidatos avaliados para exclusão por dia.

## Segurança e persistência

- Nenhuma vaga é excluída se houver favoritos, candidaturas ou outras referências pessoais ligadas à oportunidade.
- Se uma oportunidade possuir mais de uma publicação, apenas a publicação confirmada como inexistente é removida; a oportunidade permanece.
- Se todas as publicações desaparecerem e não houver referências, a oportunidade órfã é removida. As tabelas de afinidade e categoria são limpas pelas regras de integridade do SQLite.
- Antes da primeira exclusão física de cada execução, uma cópia consistente do SQLite é salva em `data/backups/*-before-retirement-*.db`. O GitHub Actions anexa essa cópia à execução por 14 dias.
- A tabela `purged_postings` conserva os IDs retirados, impedindo que novas coletas recriem os mesmos anúncios. A tabela `posting_retirement_checks` conserva as datas e contagens das verificações.
- A sincronização `tools.sync_web_catalog` aplica esses tombstones ao `radar-web.db`, mas mantém como **inativos** os anúncios com histórico pessoal (favoritos/candidaturas).

> A regra não consegue provar automaticamente o fechamento de uma vaga só porque sua descrição pública ainda existe ou porque um portal exige autenticação. Esses casos permanecem inconclusivos e nunca são apagados pelo processo.

## Como consultar e executar localmente

Pare o Spring Boot antes de acessar `web-mvc/radar-web.db`. Na raiz do repositório:

```powershell
python -m tools.retirement_cleanup --db data/opportunity_radar.db --report
python -m tools.retirement_cleanup --db data/opportunity_radar.db --apply
```

Para o banco pessoal do site, **somente se você quiser rodar a mesma política localmente**, troque o caminho:

```powershell
python -m tools.retirement_cleanup --db web-mvc/radar-web.db --report
```

A rotina principal é executada pelo GitHub Actions `Daily Opportunity Radar` automaticamente. Depois de um Daily Audit bem-sucedido, use a importação normal do snapshot para atualizar o banco do site:

```powershell
python tools/pull_classroom_db.py --output data/cleaned_latest.db
python -m tools.sync_web_catalog --from-db data/cleaned_latest.db
```

Se a versão do snapshot tiver menos vagas porque houve exclusões confirmadas, o sincronizador aceitará a redução **somente se houver registros reais em `purged_postings`**; a validação de integridade e o backup do SQLite continuam obrigatórios.

## Testar a mudança

```powershell
python -m pytest -q tests/test_retirement_cleanup.py tests/test_sync_web_catalog.py
python -m pytest -q
mvn -f web-mvc/pom.xml test
```

**Importante:** o comando de sincronização do banco do site importa apenas os registros retirados **que já constam no snapshot GitHub**. Não substitua manualmente o `radar-web.db` pelo banco baixado: contas e favoritos são armazenados no banco pessoal.
