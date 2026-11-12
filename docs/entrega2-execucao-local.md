# Entrega 2 — execução local do Opportunity Radar

Este guia é **independente da Entrega 1** e foi escrito para alguém que está baixando o projeto pela primeira vez. Os requisitos da demonstração são **banco de dados, modelagem e interface básica**.

**Repositório:** https://github.com/KuririmFestozo/opportunity-radar  
**Aplicação web:** `web-mvc/` (Java 17+, Spring Boot 3.4.3, Spring MVC, Thymeleaf, Spring Data JPA/Hibernate, Spring Security, SQLite).  
**Coleta:** módulos Python em `collectors/`, `processing/` e `storage/`.

> **Acesso:** este repositório é privado no momento da elaboração. O professor precisa ser convidado ou receber uma cópia pública revisada. Não suba bancos de dados reais, contas, hashes de senha, favoritos, tokens nem segredos para o Git.

## 1. Pré-requisitos

- Git;
- Java **JDK 17 ou superior** (versão-alvo no `pom.xml`: 17);
- Maven **3.9 ou superior**;
- Python **3** (recomendado 3.12; para gerar o banco de demonstração basta a biblioteca padrão);
- navegador e porta 8080 livre.

Verificar: `git --version`, `java -version`, `mvn -version`, `python --version`.

## 2. Iniciar o site com dados fictícios

O banco de produção não é necessário para avaliar o MVC. O script do repositório cria **seis oportunidades fictícias**, explicitamente marcadas como demonstração, em um arquivo SQLite novo.

No **Windows PowerShell**:

```powershell
git clone https://github.com/KuririmFestozo/opportunity-radar.git
cd opportunity-radar
python web-mvc/tools/create_demo_db.py web-mvc/demo-entrega2.db
$env:RADAR_DB_PATH = (Resolve-Path .\web-mvc\demo-entrega2.db).Path
mvn -f web-mvc/pom.xml spring-boot:run
```

Abra **http://localhost:8080**. O Hibernate mantém `ddl-auto=none` e a aplicação cria as tabelas próprias da interface a partir de `web-mvc/src/main/resources/db/web-schema.sql`. A inicialização valida as tabelas essenciais do catálogo.

O gerador **recusa sobrescrever** um arquivo de banco existente. Se você já criou `demo-entrega2.db`, use outro nome; não apague o banco que contém suas contas.

Em **Linux/macOS**:

```bash
git clone https://github.com/KuririmFestozo/opportunity-radar.git
cd opportunity-radar
python3 web-mvc/tools/create_demo_db.py web-mvc/demo-entrega2.db
RADAR_DB_PATH="$(pwd)/web-mvc/demo-entrega2.db" mvn -f web-mvc/pom.xml spring-boot:run
```

## 3. Funcionalidades para demonstrar

- Catálogo público em `/opportunities`: texto, curso, fonte, modalidade, localização, afinidade e verificação da inscrição;
- Detalhes em `/opportunities/{id}`: empresa, descrição, origem e pontuação;
- Cadastro `/register`, autenticação `/login` e encerramento de sessão;
- Favoritos `/favorites`, persistidos por usuário;
- Acompanhamento `/applications`, com situação e notas editáveis;
- Perfil `/profile`.

**Atenção:** `is_active` no catálogo não é prova de que inscrições estão abertas. A tabela `source_availability_checks` distingue `open`, `closed` e `unverified`; ausência de uma verificação explícita também não comprova abertura.

## 4. Executar testes

Os testes Java criam SQLite isolado e não dependem da base real:

```powershell
mvn -f web-mvc/pom.xml test
```

Para testar o pipeline Python completo (precisa baixar suas dependências):

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
python check_project.py
```

Os workflows em `.github/workflows/ci.yml` validam os módulos Python e Java a cada PR/push. Consulte [roteiro de testes](entrega2-roteiro-testes.md) para uma sequência manual, resultados esperados e casos negativos.

## 5. Opcional: carregar o catálogo real

**Somente com acesso aos Releases privados do GitHub.** Instale o GitHub CLI e autentique:

```powershell
gh auth login
python tools/pull_classroom_db.py --output data/classroom_latest.db
```

O script valida checksums e estrutura do SQLite. O arquivo completo é **separado** do banco pessoal do site e não inclui necessariamente suas contas.

Para manter contas e favoritos no banco principal, **pare o servidor** e execute `python -m tools.sync_web_catalog --from-db data/classroom_latest.db`, usando sempre `web-mvc/radar-web.db` como destino padrão. A sincronização faz backup e preserva dados pessoais; não substitua manualmente o banco principal.

## 6. Principais diretórios

| Caminho | Conteúdo |
|---|---|
| `web-mvc/pom.xml` | dependências do módulo Java |
| `web-mvc/src/main/java/.../controller/` | controladores HTTP |
| `web-mvc/src/main/java/.../domain/` | entidades JPA |
| `web-mvc/src/main/java/.../repository/` | interfaces de persistência |
| `web-mvc/src/main/java/.../service/` | regras de negócio |
| `web-mvc/src/main/resources/templates/` | HTML/Thymeleaf |
| `web-mvc/src/main/resources/db/web-schema.sql` | tabelas e índices da camada web |
| `web-mvc/src/test/` | testes Spring/SQLite |
| `collectors/`, `processing/`, `storage/` | pipeline Python |
| `tests/` | testes Python |
| `.github/workflows/` | integração contínua e auditorias |

A modelagem está resumida em [entrega2-modelagem.md](entrega2-modelagem.md). Instruções complementares: [web-mvc/README.md](../web-mvc/README.md).

## 7. Erros mais comuns

- **“SQLite não encontrado”:** gere o banco de exemplo e confira o caminho absoluto de `RADAR_DB_PATH`.
- **Login recusado após trocar de banco:** contas ficam no arquivo SQLite apontado na inicialização. Use o banco original ou sincronize somente o catálogo.
- **Porta 8080 ocupada:** encerre outro processo Spring Boot antes de iniciar.
- **Git clone/download recusado:** conceder acesso ao repositório privado; os Releases também exigem autenticação.
- **Página não permite candidatura:** links externos podem estar encerrados ou exigir login. O radar não contorna bloqueios e não presume fechamento com base apenas em HTTP 404.
