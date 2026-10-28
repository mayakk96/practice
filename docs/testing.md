# Testing strategy

## Three different questions

| Kind | Question answered | Implemented mechanism |
| --- | --- | --- |
| Unit | Does this rule behave correctly with controlled collaborators? | JUnit 5, Mockito, direct policy/service/client tests |
| Integration | Do Spring configuration, HTTP mapping, migrations, repositories and transactions work together? | `@SpringBootTest`, MockMvc, real H2/Flyway; embedded Kafka and MCP protocol tests |
| API / network HTTP | Does a started packaged application respond correctly through its actual server? | `python3 scripts/smoke_api.py` |

MockMvc executes the MVC request pipeline without starting a TCP server. It is an HTTP contract/integration test, but it does not prove that container ports, TLS, DNS or a deployed load balancer work. A network smoke test covers part of that separate boundary.

## Commands

From the repository root with a Java 21 JDK:

```sh
./mvnw test
./mvnw verify
./mvnw -Ppostgres-it verify
```

`test` runs Surefire tests. `verify` also packages the executable application and runs configured verification steps. The `postgres-it` profile enables Failsafe's PostgreSQL Testcontainers integration test, which requires Docker. It is a separate explicit check, not silently treated as passed when Docker is absent.

Reports are written to `target/surefire-reports` and `target/failsafe-reports`. Check the current run's counts, failures, errors and skipped outcomes. A successful compile or a zero-test result does not establish application readiness.

## What is covered

- The explicit lifecycle policy and service orchestration, including rejection of illegal transitions and unusable screening decisions.
- Creation/read/list/document/history HTTP contracts, status codes and DTOs.
- Missing/invalid fields, malformed JSON, enum/identifier/boundary validation and machine-readable errors.
- Real persistence, migration constraints and transaction rollback.
- Same-key replay, changed-payload conflict and concurrent idempotency arbitration.
- External request/response serialization, idempotency/correlation headers, timeout failures, transient retries and non-retryable responses.
- Durable event recording, broker transport, duplicate consumer handling and dead-letter behavior.
- The MCP initialization/tool protocol, safe outputs and bounded inputs.
- Document chunking, vector similarity, evidence selection, deterministic answers and mocked model HTTP behavior.
- Security/filter behavior and safe operational endpoints where configured.

Mockito unit tests intentionally do not prove that `@Transactional` or JPA locking works: those need a proxied Spring bean and a database. Conversely, every small rule does not need a full Spring context. Use the least expensive test that can fail for the behavior being changed.

## H2 versus PostgreSQL

The test profile runs Flyway and Hibernate validation against H2 in PostgreSQL compatibility mode. This provides fast, repeatable feedback, but H2 is not PostgreSQL: lock scheduling, SQL dialect details, query plans and constraint errors can differ.

`PostgresIntegrationIT` uses the actual PostgreSQL image via Testcontainers. CI explicitly runs that profile. For persistence-sensitive changes, run it locally before pushing. Never infer PostgreSQL correctness solely from H2 results.

## Kafka and downstream tests

An embedded broker exercises real Kafka serialization/transport/listener behavior without requiring a separately installed broker. Unit tests remain useful for failure branching and attempt limits. Broker-backed tests do not establish production replication, failover or consumer throughput.

Mocked downstream servers provide known response sequences. They let tests prove that a 400 is not retried, a transient response can recover, and attempts/timeouts are bounded. They do not certify a real vendor's contract or provider-side idempotency implementation.

## Real HTTP smoke

Start the standalone demo:

```sh
./mvnw spring-boot:run -Dspring-boot.run.profiles=demo
python3 scripts/smoke_api.py --no-auth
```

Or start Compose and use its generated credentials:

```sh
python3 scripts/create_env.py
docker compose up --build -d
python3 scripts/smoke_api.py
```

The script only sends credentials to loopback addresses. It reads the local ignored `.env` or process variables, asserts responses rather than printing sensitive bodies, and leaves a fictional completed case/history for study. A second run creates another uniquely keyed fictional case.

## CI and honest evidence

GitHub Actions runs Java 21 Maven verification, the PostgreSQL Testcontainers profile, and Compose configuration validation. Test reports are retained as artifacts. A green workflow means those checks passed for that commit; it is not a deployment, penetration test, load test or a regulatory certification.

Record environment limitations explicitly. If Docker cannot run locally, report that container checks were unrun and rely on the separate CI result only once it actually exists. Do not disable tests or replace meaningful assertions merely to obtain green output.
