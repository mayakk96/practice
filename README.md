# Enterprise Onboarding Platform

[![Build and test](https://github.com/mayakk96/practice/actions/workflows/ci.yml/badge.svg)](https://github.com/mayakk96/practice/actions/workflows/ci.yml)

An educational Java 21 / Spring Boot application for studying enterprise backend engineering through a fictional onboarding workflow. It includes a relational model, explicit business rules, safe retry behavior, durable events, read-only MCP tools, and a small policy-retrieval pipeline.

This is a portfolio and interview-practice project, with no affiliation with BNY, Discover, or any customer system. Use fictional names, `example.com` / `.test` email addresses, and synthetic document references. Documents are metadata, not uploaded identity documents. This repository contains a backend API; it does not include a browser frontend.

## Architecture

```text
REST client
    |
Spring MVC controller -> validation / Problem Details
    |
OnboardingService -> TransitionPolicy -> RiskScreeningClient -> mock HTTP service
    |
Spring Data JPA repositories
    |
PostgreSQL: applicants, cases, documents, history, idempotency claims
    |
transactional outbox -> Kafka -> idempotent audit consumer -> audit table

MCP client -> Spring AI MCP server -> read-only tools -> existing service layer

Policy files -> chunks -> feature-hash embeddings -> cosine retrieval
    -> bounded evidence context -> answer-model interface -> answer + citations
```

Controllers handle HTTP. Services own business rules and transactions. Repositories persist entities. Records describe request/response contracts; mappers keep JPA entities out of the API.

## Technology stack

| Area | Implementation |
| --- | --- |
| Application | Java 21, Spring Boot 3.5, Spring MVC, constructor injection |
| Persistence | Spring Data JPA / Hibernate, PostgreSQL, Flyway SQL migrations |
| HTTP | Jakarta Validation, DTO records, Problem Details |
| Tests | JUnit 5, Mockito, MockMvc, H2, PostgreSQL Testcontainers, embedded Kafka |
| Integration | Risk HTTP client with timeouts and bounded exponential retries |
| Events | Spring Kafka, transactional outbox, replay-safe consumer, dead-letter topic |
| Operations | Actuator, Micrometer, ECS JSON logs, request correlation IDs |
| Security | Stateless development HTTP Basic, operator/read-only roles, environment credentials |
| AI integration | Spring AI MCP over HTTP, local feature-hash embeddings, deterministic answer model, optional OpenAI-compatible HTTP model |
| Delivery | Maven wrapper, multi-stage Docker build, Compose, GitHub Actions |

## Quick start: standalone demo

Install a **Java 21 JDK**. The wrapper downloads Maven. No database, Kafka broker, or LLM key is needed for this mode.

```sh
./mvnw verify
./mvnw spring-boot:run -Dspring-boot.run.profiles=demo
```

On Windows PowerShell, use `.\mvnw.cmd` instead of `./mvnw`. The demo binds to `127.0.0.1:8080`, uses an in-memory H2 database with Flyway, disables authentication and Kafka delivery, and uses deterministic screening/policy answers. Data resets on process shutdown. Outbox rows are still recorded transactionally.

In another terminal:

```sh
python3 scripts/smoke_api.py --no-auth
```

The smoke script exercises real HTTP, idempotency, lifecycle rules, duplicate documents, history and error responses. It leaves one fictional completed case for inspection.

## PostgreSQL and Kafka through Docker

Install Docker with the Compose plugin and Python 3, then run:

```sh
python3 scripts/create_env.py
docker compose up --build -d
docker compose ps
python3 scripts/smoke_api.py
```

The first command generates local database/operator/reader credentials in ignored `.env` without printing values. It refuses to overwrite an existing file. Alternatively, copy `.env.example` to `.env` and fill the empty credential values.

| Service | Purpose / access |
| --- | --- |
| `app` | API/MCP at `127.0.0.1:8080`, authentication enabled |
| `postgres` | PostgreSQL 17 at `127.0.0.1:5432`, persistent named volume |
| `kafka` | Single KRaft broker; host clients use `localhost:9094` |
| `mock-risk` | Fictional screening service, internal to Compose |

Infrastructure health checks gate app startup. The app's health check makes an HTTP health request. Kafka is a single-node, plaintext, ephemeral demonstration broker; recreating it loses broker storage. PostgreSQL survives container replacement until its volume is removed.

```sh
docker compose logs -f app
docker compose down
# Destructive reset of this local demo database:
docker compose down -v
```

To run from an IDE against Compose PostgreSQL, start `docker compose up -d postgres kafka mock-risk`, set `DATABASE_URL`, `DATABASE_USERNAME`, `DATABASE_PASSWORD`, `APP_API_USERNAME` and `APP_API_PASSWORD` in the IDE, and run the `postgres` profile. Kafka delivery is opt-in: `APPLICATION_EVENTS_ENABLED=true` and `KAFKA_BOOTSTRAP_SERVERS=localhost:9094`. Screening defaults to a deterministic stub; HTTP mode uses `APPLICATION_SCREENING_MODE=http` and a reachable `APPLICATION_SCREENING_BASE_URL`.

## API

The example below targets the unauthenticated demo. For secured Compose add `--user operator`; curl prompts for the generated operator password stored in your local `.env`.

```sh
curl -i http://127.0.0.1:8080/api/onboarding/cases \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: interview-demo-001' \
  -d '{"firstName":"Demo","lastName":"Applicant","email":"demo@example.com","assignedTeam":"ONBOARDING"}'
```

Use the returned UUID in later requests. A replay with the same key/body returns `200` and `Idempotency-Replayed: true`; a different body with the same key returns `409`.

| Method | Endpoint | Successful behavior |
| --- | --- | --- |
| POST | `/api/onboarding/cases` | `201` create; `200` idempotent replay |
| GET | `/api/onboarding/cases?page=0&size=20` | Paginated list; size bounded to 1–100 |
| GET | `/api/onboarding/cases/{id}` | Case details |
| PATCH | `/api/onboarding/cases/{id}/status` | Validated status change |
| POST | `/api/onboarding/cases/{id}/documents` | Document metadata submission |
| GET | `/api/onboarding/cases/{id}/history` | Ordered status history |
| POST | `/api/knowledge/search` | Policy answer with evidence citations |
| POST | `/mcp` | MCP JSON-RPC endpoint |
| GET | `/actuator/health`, `/actuator/info` | Safe aggregate health / info |
| GET | `/actuator/health/readiness` | Application/database readiness |
| GET | `/actuator/metrics`, `/actuator/prometheus` | Operator metrics |

Status body: `{"status":"DOCUMENTS_PENDING","reason":"Requested fictional documents"}`.
Document body: `{"documentType":"IDENTITY_PROOF","reference":"DEMO-IDENTITY-001"}`.

```text
CREATED -> DOCUMENTS_PENDING -> UNDER_REVIEW -> APPROVED -> COMPLETED
                                      |
                                      +-> RISK_REVIEW -> APPROVED / REJECTED
                                      +-> REJECTED
```

`REJECTED` and `COMPLETED` are terminal. Reviewers may return `UNDER_REVIEW` or `RISK_REVIEW` to `DOCUMENTS_PENDING` with an audited reason to request more documents. Submit documents while `CREATED` or `DOCUMENTS_PENDING`. Approval requires both `IDENTITY_PROOF` and `ADDRESS_PROOF` and a low/medium screening result. High-risk cases cannot be approved. A failed downstream call does not partially commit a transition.

## Persistence, errors and idempotency

Flyway versions the schema; Hibernate uses `ddl-auto=validate`. UUID primary keys, foreign keys, enum checks, uniqueness and query-oriented indexes are explicit in migrations. [Architecture notes](docs/architecture.md) explain index and transaction choices.

An idempotency claim stores a unique key and SHA-256 fingerprint of the normalized request. Claim, applicant, case, history and outbox commit together. A concurrent loser rolls back before reading the winner in a new transaction. Correctness comes from the database, not a JVM lock. Claims currently have no expiry; production requires a retention/replay policy.

Machine-readable Problem Details distinguish validation `400`, missing resource `404`, business conflict `409`, rejected downstream response `502` and unavailable screening `503`. Responses do not expose stack traces or downstream bodies.

## Security and observability

The PostgreSQL profile enables HTTP Basic: an operator can mutate cases, while an optional reader can use read-only REST/MCP. Knowledge search is read-only despite using POST. Health/info are public; metrics require the operator. Credentials come from environment variables. The loopback demo disables authentication.

Actuator exposes health/readiness and controlled metrics. ECS JSON logs carry correlation IDs and workflow IDs/statuses, rather than names, email, document references or policy queries. See [observability](docs/observability.md).

This demonstrates boundaries, not enterprise identity infrastructure. Production needs TLS, centralized OIDC/OAuth2, tenant/object authorization, managed secrets, rate limits and security review.

## External client and events

`RiskScreeningClient` isolates HTTP serialization, headers, response validation, timeouts and error translation. Only transient failures are retried, with a bounded exponential delay and stable downstream idempotency key. See [external client](docs/external-client.md).

A separate outbox dispatcher waits for Kafka acknowledgement before marking delivery. A crash in between can resend an event: the audit consumer deduplicates by event UUID. Events use case UUID keys and a versioned metadata-only envelope. Consumer failures have bounded retries and a dead-letter topic. See [event design](docs/events.md); this is at-least-once processing, not an exactly-once claim.

## MCP and foundational RAG

Read-only tools look up sanitized cases, list pending cases, inspect status history and search policy. Handlers delegate to existing services. MCP is a model-facing adapter; REST, service rules and transactions remain the application foundation.

Policy search ingests bundled fictional documents, chunks them, builds 512-dimensional signed feature-hash embeddings, retrieves by cosine similarity, constructs bounded evidence context, calls an answer-model interface and returns citations. The default generator is deterministic and needs no key. Feature hashing is a lexical embedding baseline, not a pretrained semantic model; a citation does not prove a model answer is true.

```sh
curl http://127.0.0.1:8080/api/knowledge/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Which documents are required before approval?","topK":3}'
```

Optional HTTP model settings are `APPLICATION_KNOWLEDGE_MODE=http`, `APPLICATION_KNOWLEDGE_BASE_URL`, `APPLICATION_KNOWLEDGE_MODEL` and `APPLICATION_KNOWLEDGE_API_KEY` when required by the provider. Compose forwards these optional `.env` settings; use a provider URL reachable from the application container (its `localhost` refers to that container). No model server is bundled. [MCP/RAG notes](docs/ai-mcp.md) document the verified library choice, protocol usage and limitations.

## Tests and CI

```sh
./mvnw test
./mvnw verify
# Requires Docker:
./mvnw -Ppostgres-it verify
```

Unit tests isolate business rules with Mockito. MockMvc integration tests exercise Spring HTTP handling and real H2/Flyway persistence. PostgreSQL Testcontainers verify PostgreSQL-specific behavior. Embedded Kafka tests exercise broker transport/replay. The smoke script checks actual network HTTP. [Testing notes](docs/testing.md) explain what each proves.

GitHub Actions runs verification, PostgreSQL container tests and Compose validation, and retains reports. It builds and tests; it does not deploy an environment.

## Study path and production considerations

Start with [CODE_WALKTHROUGH](docs/CODE_WALKTHROUGH.md), [architecture](docs/architecture.md), then [INTERVIEW_GUIDE](docs/INTERVIEW_GUIDE.md). Read the client/events/MCP notes before discussing distributed or AI guarantees.

Before production: centralized identity and object authorization; Kafka TLS/SASL and replication; backup/restore drills; operational migrations; privacy/retention policies; managed secrets; event schema compatibility; capacity testing; outage exercises; tracing and alerts; and evaluated embedding/model providers. Synchronous screening holds a bounded database transaction and needs redesign for a long-running real process. No financial compliance or production suitability is claimed.
