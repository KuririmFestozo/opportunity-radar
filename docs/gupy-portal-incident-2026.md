# Gupy public portal — incidente de novembro de 2026

Observado nos logs GitHub Actions em 03, 04 e 05/11:
https://github.com/KuririmFestozo/opportunity-radar/actions/runs/42007883738

O endpoint anterior (employability-portal.gupy.io/api/v1/jobs) responde HTTP 404.
A pesquisa global muda para a rota pública utilizada pelo portal de candidatos:
https://portal.gupy.io/api/job-search/jobs (não documentada como contrato estável).

A implementação preserva as identidades e a coleta conservadora:
- Não confunde 404 com erro de filtro.
- Não transforma resposta com esquema desconhecido em lista vazia.
- Em caso de exceção, o escopo não deve ser considerado varredura completa
  para inativação. O histórico já armazenado não é apagado.
- O coletor Gupy por empresa e a API oficial token-scoped continuam separados.

**Verificação necessária:** depois do merge, conferir a coleta real seguinte.
Não há garantia de estabilidade da API pública. Se a rota estiver indisponível,
o erro permanece explícito; não marcar vagas como encerradas só pela falha.

A falha isolada HTTP 504 no Vagas.com em 05/11 é transiente do servidor.
O módulo collectors/common.py já faz retries limitados para 504.
Evitar fixes que transformem timeout em sucesso/catálogo vazio.

A janela de resultados do portal tem limite aproximado de 10 mil vagas. A
paginação foi limitada antes do offset 10000; se esse limite for atingido sem
página curta, o coletor emite aviso de cobertura potencialmente parcial.

O sistema também executa as três páginas Gupy corporativas configuradas como
contingência, com limite de detalhes, quando o coletor global falha ou não
retorna vagas. Essa ação conserva `source=gupy_public`; não inventa IDs do portal
nem conclui lifecycle da Gupy Global. Pode ser desabilitada em
`gupy_public_fallback.on_global_failure`.
