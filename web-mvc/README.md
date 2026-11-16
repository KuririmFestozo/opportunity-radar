# Opportunity Radar — Web MVC (PostgreSQL)

A aplicação web utiliza **Spring Boot 3.4.3, Java 17, Spring MVC, Thymeleaf,
Spring Security com BCrypt, Spring Data JPA/Hibernate e PostgreSQL 16**.
O visual SIGNAL está preservado.

## Executar do zero

Na raiz do repositório, com Docker Desktop em execução:

```sh
docker compose up --build
```

Abra http://localhost:8080/opportunities. O banco de demonstração é semeado
com seis vagas fictícias automaticamente e persiste em volume Docker.

**Roteiro completo:** [../docs/entrega2-execucao-local.md](../docs/entrega2-execucao-local.md).

## Testar

```sh
mvn -f web-mvc/pom.xml test
```

Requer Docker Desktop porque os testes usam Testcontainers PostgreSQL isolado.
O SQLite permanece exclusivamente nos coletores Python antigos e em snapshots.
