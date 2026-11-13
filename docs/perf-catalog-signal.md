# Otimização conservadora do catálogo web SIGNAL

O protótipo com dezenas de milhares de oportunidades podia demorar para abrir `/opportunities`. O CSS do SIGNAL não participa das consultas SQL.

## Alterações

- Índice por publicação/atualização, por pontuação máxima por oportunidade e por coordenadas; índices criados no SQLite **do site** pela inicialização do Spring, sem alterar tabelas ou registros pessoais.
- `CatalogService` reutiliza temporariamente opções de filtro e total (TTL 2 minutos) em vez de consultar de novo a cada visita.
- `AdvancedSearchService.intents()` reutiliza temporariamente os tipos de oportunidade (TTL 2 minutos).
- Busca com coordenadas **e raio definido** faz um recorte geográfico conservador no SQL antes de ordenar distâncias no Java. O filtro Haversine exato continua igual. O recorte considera a linha internacional de mudança de data, polos e a opção de incluir vagas remotas sem coordenadas.

## Limitações

- Ordenação por afinidade sem raio ainda precisa calcular pontuações no catálogo; essa otimização não garante tempo de resposta específico na base completa.
- O banco SQLite fica maior por conta dos índices, montados uma vez na inicialização. Na primeira partida após a alteração, o startup pode demorar mais.
- Mudar dados do banco enquanto o Spring está ativo não é recomendado, e metadados em cache podem ficar até 2 minutos desatualizados em um ambiente de desenvolvimento.
- Em consultas geográficas **sem raio**, a aplicação ainda precisa examinar todos os candidatos para ordená-los corretamente por distância.

## Verificação

```powershell
git switch perf/signal-catalog-speed
$env:RADAR_DB_PATH = (Resolve-Path .\web-mvc\radar-web.db).Path
mvn -f web-mvc/pom.xml test
mvn -f web-mvc/pom.xml spring-boot:run
```

Teste `/opportunities` inicialmente, com curso, disponibilidade, proximidade/raio e login/favoritos.
