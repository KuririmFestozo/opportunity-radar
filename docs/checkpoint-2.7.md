# Checkpoint 2.7 — ATS e cobertura regional

Verificação pública em 18/09/2026. Nenhuma autenticação, candidatura ou
persistência foi usada nos diagnósticos ao vivo.

## Fontes regionais

| Empresa | Evidência pública / resultado | Integração |
|---|---|---|
| Xmobots | [TOTVS](https://atracaodetalentos.totvs.app/xmobotscarreiras): 5 vagas no HTML, com UUID, código e links próprios. Detalhes confirmados em São Carlos. | Novo coletor TOTVS genérico; tenant é um caminho, não subdomínio. |
| Tecumseh | [Carreiras](https://careers.tecumseh.com/jobs): assets Teamtailor, links `/jobs/show_more?page=2` e JobPosting JSON-LD. 32 vagas na verificação, incluindo estágio São Carlos `8382079`. | Novo coletor Teamtailor genérico sobre HTML público. |
| Citrosuco | [Carreiras](https://carreiras.citrosuco.com.br/): scripts SAP/RMK; parser existente leu 5 vagas na primeira página de tiles, incluindo Matão. | Tenant SuccessFactors existente; sem scraper próprio. |
| Volkswagen Group | [Portal](https://jobs.volkswagen-group.com/): scripts SuccessFactors; parser existente leu 25 vagas na primeira página de tiles. | Tenant SuccessFactors. Compatibilidade do portal confirmada; cobertura de Volkswagen São Carlos ainda não confirmada. |
| Serasa Experian | [API pública oficial](https://api.smartrecruiters.com/v1/companies/Experian/postings): company identifier `Experian`; 14 vagas com cidade São Carlos entre os primeiros 100 resultados da consulta diagnóstica. | Primeiro board SmartRecruiters, catálogo amplo, independente de curso. |
| Faber-Castell | Diagnóstico do endpoint Gupy Global: 2 registros no recorte São Carlos, incluindo `12278134`. | Sem coletor novo. |
| TATU Marchesan | Diagnóstico do endpoint Gupy Global: 6 registros no recorte Matão, incluindo `11304276`. | Sem coletor novo. |
| Raízen | [Página oficial](https://www.raizen.com.br/programas-de-talentos) aponta para `genteraizen.gupy.io`. | Gupy identificado; cobertura Araraquara/Ibaté não verificada neste recorte. |
| Amdocs | [Portal oficial](https://jobs.amdocs.com/) redireciona para `/careers` e referencia `app.eightfold-eu.ai`. | Eightfold identificado; integração pendente. |
| Electrolux | [Portal oficial](https://career.electroluxgroup.com/) redireciona para `/global/en` e contém Phenom. | Frontend Phenom identificado; ATS subjacente e integração pendentes. |
| Lupo | [Trabalhe conosco](https://www.lupo.com.br/trabalhe-conosco) sem evidência suficiente de ATS no HTML consultado. | Pendente; nenhum scraper criado. |

## Incremental e limites

- Citrosuco e Volkswagen: o coletor targeted existente retornou respectivamente
  2 e 10 vagas no teste limitado com `aprendiz`. A rota CSB JSON retornou 401;
  esses tenants usam as rotas públicas HTML/RMK já suportadas, com CSB JSON
  desativado. Não foi tentado contornar autenticação.
- InHire: uma chamada ao catálogo público do frontend; estatísticas de IDs.
- IziRH: configuração + páginas do endpoint público do frontend, com
  `createdAt desc`; parada após duas páginas consecutivas conhecidas. Um ID
  novo reinicia a contagem; páginas repetidas também encerram a consulta.
- Workday: endpoint CXS público usado pelo frontend; mantém queries early-career,
  deduplicação global e limites. Sem parada por IDs conhecidos porque não há
  garantia de ordenação por recência.
- SmartRecruiters: Posting API oficial; `q` mantido. Consultas reais com
  `estágio`, `intern` e um termo inexistente produziram resultados diferentes.
  Bosch: 25 / 1320 / 0; Aumovio: 25 / 185 / 0. O teto de 250 é aplicado a IDs
  únicos e não foi aumentado. Há aviso quando esse teto é atingido.
- `releasedAfter` não foi ativado: `releasedDate` por vaga não representa um
  checkpoint completo da fonte. A coleta existente é limitada por páginas,
  queries e quantidade; usar a maior data persistida pode omitir vagas.
- Workday e SmartRecruiters encerram páginas vazias/repetidas por query, sem
  confundir sobreposição entre queries com repetição de página.
- TOTVS: catálogo observado em uma resposta, com filtragem no navegador.
  Não foi inventada paginação ou ordenação cronológica. O caminho rápido
  consulta o catálogo e evita detalhes conhecidos; nunca para em um ID conhecido.
- Teamtailor: segue somente links públicos de paginação; encerra em ausência de
  resultados/próxima página, repetição ou limites. Não aplica parada cronológica.
- TOTVS/Teamtailor usam HTML público, não uma API oficial de integração; mudanças
  no contrato de HTML podem exigir manutenção. Detalhes usam JSON-LD; TOTVS
  complementa com descrição, responsabilidades, requisitos e regime visíveis.
  O atributo TOTVS `data-remote-string` é apenas um rótulo e não define modalidade.
- IDs conhecidos continuam sendo entregues ao JobStore. Campos inalterados
  reutilizam classificação/geolocalização; mudanças no conteúdo retornado são
  processadas. Detalhes de vagas conhecidas podem ficar desatualizados até um
  `FULL_REFRESH=1`, que também desativa a parada por páginas conhecidas.
- Os cadastros adicionais solicitados foram adicionados. Não foi feita uma
  coleta integral de cada board. Tetos de páginas/vagas/detalhes continuam
  sendo limites reais de cobertura, inclusive no full refresh.

## Diagnóstico reproduzível Gupy

```powershell
python check_regional_sources.py
python check_regional_sources.py --live
```

O primeiro lê `output/jobs.json`; o segundo reutiliza o segmento do coletor
Gupy Global em no máximo duas páginas por cidade, sem gravar no banco ou
exportar arquivos. Confirma presença no endpoint global, não inclusão automática
no lote agendado: os resultados observados incluem vagas fora do recorte
early-career. Não há filtro regional novo no pipeline agendado.
