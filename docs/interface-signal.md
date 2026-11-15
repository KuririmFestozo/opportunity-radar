# SIGNAL — identidade visual alternativa do Opportunity Radar

Este tema é um design original desenvolvido para o projeto, com linguagem editorial e foco em legibilidade e hierarquia de informação. Não foi copiado de template externo.

## Conceito

- Tipografia: Space Grotesk nos títulos, DM Sans no corpo, IBM Plex Mono nos controles e metadados.
- Paleta: fundo areia, tinta grafite, realce laranja e painel de geolocalização azul.
- Catálogo: lista horizontal numerada em vez de cartões verdes em três colunas.
- Filtros: painel com campos em grade e bordas retas.
- Detalhes: cabeçalho escuro com contraste forte; formulários e históricos no mesmo sistema visual.
- Responsivo: adapta para tablet e celular; inclui foco visível e respeito a reduced motion.

## Arquivos

- `web-mvc/src/main/resources/static/css/signal.css`: tema, isolado do estilo anterior.
- Templates em `web-mvc/src/main/resources/templates/`: recebem somente um link CSS adicional.
- `fragments/nav.html`: ajuste decorativo no símbolo da marca.
- `opportunities.html`: título e chamada da capa renovados.

Nenhuma rota, nome de campo, método HTTP, regra de autenticação, SQL ou tabela de usuário foi alterada.

## Como testar sem afetar main

```powershell
git fetch origin
git switch feat/signal-editorial-redesign
mvn -f web-mvc/pom.xml test
$env:RADAR_DB_PATH = (Resolve-Path .\web-mvc\radar-web.db).Path
mvn -f web-mvc/pom.xml spring-boot:run
```

Abra `http://localhost:8080`. Confira também `/login`, `/register`, `/favorites`, `/applications` e `/profile` após autenticação.

**Observação:** para voltar ao visual anterior, basta retornar à `main` (sem mesclar esta branch). O site pode continuar lento na busca por distância com dezenas de milhares de vagas; este tema não modifica o desempenho das consultas.

**Atribuição:** tema visual original criado para Opportunity Radar, sem componentes comerciais ou assets de terceiros. Fontes web entregues pelo Google Fonts, com fallbacks locais.
