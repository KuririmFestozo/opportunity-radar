# Entrega 2 — roteiro de testes do Opportunity Radar

Use o procedimento de [execução local](entrega2-execucao-local.md) para criar um **SQLite fictício** e iniciar o site. Não execute estes testes sobre um arquivo de banco com contas reais.

## Testes manuais de aceitação

| ID | Procedimento | Resultado esperado |
|---|---|---|
| T01 | Criar banco com `create_demo_db.py` e iniciar Spring Boot | Servidor em `http://localhost:8080`; sem falha de esquema |
| T02 | Acessar `/opportunities` | Lista de vagas fictícias com título, empresa e paginação |
| T03 | Pesquisar texto presente em uma das seis vagas | Itens filtrados conforme o termo |
| T04 | Alterar curso, modalidade ou fonte | Filtro aplicado; pode retornar vazio na demo reduzida |
| T05 | Abrir `/opportunities/{id}` a partir da listagem | Detalhes da vaga, origem e pontuação de afinidade |
| T06 | Acessar `/favorites` sem autenticação | Redirecionamento ao login |
| T07 | Cadastrar conta em `/register` com dados válidos | Conta criada; login passa a ser permitido |
| T08 | Repetir usuário já cadastrado ou usar senha inválida | Erro de validação, sem duplicação |
| T09 | Tentar entrar com senha errada | Acesso negado sem exposição da senha |
| T10 | Entrar corretamente e adicionar/remover favorito | Lista pessoal atualizada; vaga original permanece |
| T11 | Salvar candidatura com status e nota | Registro disponível em `/applications` |
| T12 | Editar status e nota | Alterações persistidas |
| T13 | Excluir candidatura | Registro pessoal removido; vaga permanece |
| T14 | Fazer logout e acessar página protegida | Nova autenticação exigida |
| T15 | Reiniciar o servidor **com o mesmo SQLite** | Conta, favoritos e candidaturas preservados |

**Observação:** as vagas de demonstração são fictícias. Não usar seus links externos para candidaturas reais. Algumas consultas de localização dependem de permissão de geolocalização do navegador.

## Testes automatizados

**Módulo web Java:**

```powershell
mvn -f web-mvc/pom.xml test
```

Incluem integração Spring MVC, Thymeleaf, autenticação/BCrypt, proteção contra CSRF, filtros, URLs, índices, favoritos e CRUD de candidaturas. As classes de teste criam SQLite temporário, não substituem `radar-web.db`.

**Pipeline Python:**

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
python check_project.py
```

Abrangem deduplicação, integridade incremental, esquema relacional, coletoras multi-fonte e status de disponibilidade. O número de testes pode mudar entre commits; consulte a execução do commit entregue em **GitHub → Actions → CI**.

## Critérios de aceitação

1. Instalação e execução local reproduzíveis **sem copiar o banco real**.
2. Catálogo legível e consulta por filtros funcionais.
3. Classes `@Entity` mapeadas ao SQLite existente com JPA/Hibernate.
4. Autenticação e isolamento entre contas; senhas não armazenadas em texto puro.
5. Favoritos e candidaturas persistidos entre reinicializações do servidor.
6. Nenhuma alteração/eliminação de vagas históricas ao remover favoritos ou candidaturas.
7. Identificação explícita de disponibilidade inconclusiva: uma descrição acessível não equivale a inscrições abertas.
8. Testes automatizados executáveis pelos comandos acima.

## Evidências para a apresentação

Mostrar (i) `mvn test` finalizando com sucesso; (ii) terminal do Spring Boot; (iii) catálogo e filtros; (iv) formulário de cadastro/login; (v) favorito e candidatura persistidos após recarregar; (vi) esquema SQL e classes JPA no IDE; (vii) link do repositório.

Não inserir prints de tela fabricados: todas as evidências devem ser capturadas da versão executada pelo grupo.
