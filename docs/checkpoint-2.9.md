# Checkpoint 2.9 — fontes brasileiras de estágio e início de carreira

Pesquisa pública realizada em 18/09/2026.

## Princípio

As integrações usam somente conteúdo público sem login. Perfis/cursos não restringem coleta. APIs comerciais ou áreas autenticadas não são contornadas.

| Fonte | Estado | Superfície usada | Cobertura |
|---|---|---|---|
| WallJobs | ativa | `app.walljobs.com.br/vagas` + home pública como fallback | cards públicos |
| Companhia de Estágios | ativa | página pública de programas | programas abertos; sem API comercial |
| Nube | ativa | busca avançada pública | vagas públicas com código nativo |
| IEL | ativa | IEL Carreiras nacional/UF | catálogo público nacional, extensível por UF |
| Cia de Talentos | collector pronto, desativado | hydration/HTML público | painel dinâmico; contrato estável ainda não confirmado |
| Super Estágios | collector pronto, desativado | páginas SEO públicas configuradas | catálogo nacional sem identidade pública robusta confirmada |

## Incremental

IDs conhecidos são passados pelo orquestrador. Nenhuma fonte deste checkpoint usa early-stop cronológico sem ordenação pública comprovada. O JobStore continua responsável por detectar conteúdo inalterado/alterado.

## Limitações

- Companhia de Estágios: a superfície pública enfatiza programas; vagas individuais completas podem exigir cadastro.
- Cia de Talentos: manter desativada até confirmar um endpoint/contrato público estável.
- Super Estágios: manter desativada até confirmar identidade pública nacional confiável por vaga.
