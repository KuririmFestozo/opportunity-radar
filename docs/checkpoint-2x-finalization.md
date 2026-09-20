# Fechamento do bloco 2.x — cobertura sem truncamento + incremental seguro

## Sem truncamento de produto

Workday, SmartRecruiters e SuccessFactors targeted usam `0` como "sem teto de
produto". Os collectors continuam com guard rails altos contra paginação
quebrada: 200 páginas/query e 10.000 jobs únicos por fonte/run. Atingir um guard
rail deve produzir `[LIMIT]`.

## Query-scoped recall

Resultados de uma query explicitamente early-career são preservados mesmo que o
título visível não contenha a palavra buscada; o match pode existir em descrição
ou metadata que o card não expõe.

## SuccessFactors query early-stop

Depois do baseline completo, runs normais interrompem uma query targeted depois
de 5 páginas recentes consecutivas contendo apenas IDs conhecidos. O mecanismo é
desabilitado em `FULL_REFRESH` e `FULL_DISCOVERY`.

## FULL_DISCOVERY

`FULL_DISCOVERY=1` faz um baseline de cobertura sem FAST-stop global do
SuccessFactors e sem early-stop por query. Ele não reseta o banco e continua
reaproveitando detalhes conhecidos. Deve ser rodado uma vez após remover os
tetos antigos para preencher eventuais lacunas históricas.
