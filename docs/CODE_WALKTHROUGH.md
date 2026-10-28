# Code walkthrough

Read this beside the source and follow one request all the way to the database. The application is a modular monolith: packages separate responsibilities, while one service layer owns the workflow.

## 1. Start with configuration

| File | What to understand |
| --- | --- |
| [pom.xml](../pom.xml) | Java 21, Boot-managed dependencies, MCP compatibility version, Surefire/Failsafe and packaging |
| [PracticeApplication](../src/main/java/com/example/practice/PracticeApplication.java) | Starts Boot and component scanning |
| [application.properties](../src/main/resources/application.properties) | PostgreSQL default, Hibernate validation, Flyway, Actuator, JSON logs, integration/security defaults |
| [application-demo.properties](../src/main/resources/application-demo.properties) | Loopback-only, no-key H2/stub/no-auth mode; disposable database |
| [application-postgres.properties](../src/main/resources/application-postgres.properties) | PostgreSQL pool behavior; database credentials supplied externally |
| [test profile](../src/test/resources/application-test.properties) | Isolated H2/Flyway context, no external service requirement |

Profile selection changes infrastructure, not the business policy. A green H2 demo does not prove PostgreSQL-specific behavior; that is why the container test exists.

## 2. Follow POST /api/onboarding/cases

1. `RequestLoggingFilter` creates/validates a request ID and establishes logging context.
2. `SecurityConfiguration` authenticates/authorizes the request when security is enabled.
3. `OnboardingController.create` deserializes `CreateCaseRequest` and triggers validation.
4. `OnboardingService.createCase` validates the optional key, normalizes input and fingerprints it.
5. A `TransactionTemplate` starts the claim/create transaction.
6. Repositories persist the applicant, case and initial history; a matching existing claim replays the same case.
7. `JpaDomainEventRecorder` writes the creation event in that same transaction.
8. `OnboardingMapper` creates `CaseResponse` before the persistence context closes.
9. The controller returns `201` with Location, or `200` and a replay header.
10. The filter writes a safe request-completion log and clears its MDC state.

Open these files first:

| Class | Responsibility |
| --- | --- |
| [OnboardingController](../src/main/java/com/example/practice/onboarding/api/OnboardingController.java) | HTTP routes, request/header binding and status/Location responses |
| [CreateCaseRequest](../src/main/java/com/example/practice/onboarding/api/CreateCaseRequest.java) | Required/length/fictional-email/team constraints |
| [OnboardingService](../src/main/java/com/example/practice/onboarding/service/OnboardingService.java) | Business orchestration, transaction boundaries, idempotency and locking |
| [OnboardingMapper](../src/main/java/com/example/practice/onboarding/service/OnboardingMapper.java) | Explicit conversion from entities to public DTOs |
| [CaseResponse](../src/main/java/com/example/practice/onboarding/api/CaseResponse.java) | Stable REST output shape |
| [CaseCreationResult](../src/main/java/com/example/practice/onboarding/api/CaseCreationResult.java) | Separates business replay outcome from HTTP status selection |

The important concurrency branch is the unique claim insert. A competing transaction can lose; the service catches that failure only after rollback and reads the committed winner using a new transaction. Look for why continuing inside the failed transaction would be wrong on PostgreSQL.

`IdempotencyRequest` implements `Persistable<String>` to force INSERT for a new application-assigned key. `AuditEvent` uses the same pattern. Study `IdempotencyClaimRaceIntegrationTest` and `AuditInsertRaceIntegrationTest`: they deliberately commit a competing request after the first lookup but before the delayed insert. Ordinary simultaneous requests do not reliably exercise this timing window.

## 3. Inspect the relational model

| Class / migration | Responsibility |
| --- | --- |
| [Applicant](../src/main/java/com/example/practice/onboarding/model/Applicant.java) | Fictional applicant fields and creation timestamp |
| [OnboardingCase](../src/main/java/com/example/practice/onboarding/model/OnboardingCase.java) | Applicant relationship, state/risk/team, timestamps and version |
| [CaseDocument](../src/main/java/com/example/practice/onboarding/model/CaseDocument.java) | Metadata for one required document type, linked to a case |
| [StatusHistory](../src/main/java/com/example/practice/onboarding/model/StatusHistory.java) | Previous/new states, reason and timestamp |
| [IdempotencyRequest](../src/main/java/com/example/practice/onboarding/model/IdempotencyRequest.java) | Request key, fingerprint and resulting case ID |
| [OnboardingCaseRepository](../src/main/java/com/example/practice/onboarding/repository/OnboardingCaseRepository.java) | Case queries, pending-state filtering and mutation lock query |
| [V1](../src/main/resources/db/migration/V1__initial_schema.sql) | Domain constraints, indexes and idempotency table |
| [V2](../src/main/resources/db/migration/V2__add_status_history.sql) | History table and ordered history index |
| [V3](../src/main/resources/db/migration/V3__event_outbox_and_audit.sql) | Outbox and replay-safe audit persistence |

Find each foreign key and uniqueness constraint in SQL. Explain which invariant would still hold if two application instances raced. Then compare those guarantees with Java precondition checks.

## 4. Trace an approval and a failure

`changeStatus` loads a locked case, checks `TransitionPolicy`, verifies document types, and calls screening when approval is requested. It updates the case, appends history and records an event in one transaction. A high-risk decision or unavailable provider prevents the transition from committing.

| Class | Responsibility |
| --- | --- |
| [TransitionPolicy](../src/main/java/com/example/practice/onboarding/service/TransitionPolicy.java) | Allowed edges in one explicit map |
| [ChangeStatusRequest](../src/main/java/com/example/practice/onboarding/api/ChangeStatusRequest.java) | Required target state and bounded nonblank reason |
| [SubmitDocumentRequest](../src/main/java/com/example/practice/onboarding/api/SubmitDocumentRequest.java) | Required enum type and safe synthetic reference |
| [BusinessConflictException](../src/main/java/com/example/practice/onboarding/service/BusinessConflictException.java) | Valid requests that conflict with current business state |
| [GlobalExceptionHandler](../src/main/java/com/example/practice/api/GlobalExceptionHandler.java) | Consistent Problem Details without leaking internal/remote error text |

Try returning from review to documents-pending with a reason, then submitting the missing document and re-entering review. Try CREATED directly to COMPLETED and explain the resulting `409`.

## 5. Follow the external client

| Class / file | Responsibility |
| --- | --- |
| [RiskScreeningClient](../src/main/java/com/example/practice/screening/RiskScreeningClient.java) | Small application-facing integration interface |
| [HttpRiskScreeningClient](../src/main/java/com/example/practice/screening/HttpRiskScreeningClient.java) | HTTP DTOs, headers, timeouts, retry loop and sanitized error mapping |
| [ScreeningProperties](../src/main/java/com/example/practice/screening/ScreeningProperties.java) | Validated base URL, attempts and timing bounds |
| [ScreeningConfiguration](../src/main/java/com/example/practice/screening/ScreeningConfiguration.java) | Chooses deterministic stub or real HTTP adapter |
| [server.py](../demo/risk-service/server.py) | Local fictional provider and controlled failure/delay scenarios |

Read one successful HTTP test, one non-retried bad response, and one timeout test. The stable case UUID/idempotency header matters because a timeout can occur after the provider has already acted.

## 6. Follow an outbox event

| Class | Responsibility |
| --- | --- |
| [DomainEvent](../src/main/java/com/example/practice/events/DomainEvent.java) | Versioned envelope with event/case IDs, type, time and metadata |
| [DomainEventRecorder](../src/main/java/com/example/practice/events/DomainEventRecorder.java) | Business-facing event-recording interface |
| [JpaDomainEventRecorder](../src/main/java/com/example/practice/events/JpaDomainEventRecorder.java) | Requires the business transaction and writes the durable outbox |
| [EventMetadata](../src/main/java/com/example/practice/events/EventMetadata.java) | Allowed metadata boundaries and validation |
| [OutboxEvent](../src/main/java/com/example/practice/events/OutboxEvent.java) | Delivery state, sequence, attempts and next attempt time |
| [OutboxDispatcher](../src/main/java/com/example/practice/events/OutboxDispatcher.java) | Conditional scheduled dispatch trigger |
| [OutboxDeliveryService](../src/main/java/com/example/practice/events/OutboxDeliveryService.java) | Ordered delivery, bounded acknowledgement waiting and retry state |
| [OnboardingKafkaConfiguration](../src/main/java/com/example/practice/events/OnboardingKafkaConfiguration.java) | Topics, listener factory, retry/DLT policy |
| [OnboardingAuditConsumer](../src/main/java/com/example/practice/events/OnboardingAuditConsumer.java) | Transport handler that validates and delegates audit work |
| [AuditEventService](../src/main/java/com/example/practice/events/AuditEventService.java) | Database-backed idempotent audit effect |

Draw the crash interval after a broker acknowledgement and before the delivered marker commits. Then find the unique audit-event key that makes that replay safe. Explain why Kafka producer idempotence alone does not close a cross-system database crash window.

## 7. Follow policy search

| Class / resource | Responsibility |
| --- | --- |
| [knowledge resources](../src/main/resources/knowledge/) | Four safe fictional policy documents |
| [PolicyDocumentLoader](../src/main/java/com/example/practice/knowledge/PolicyDocumentLoader.java) | Ingests resources into 80-word chunks with 15-word overlap |
| [EmbeddingModel](../src/main/java/com/example/practice/knowledge/EmbeddingModel.java) | Provider-independent embedding boundary |
| [HashingEmbeddingModel](../src/main/java/com/example/practice/knowledge/HashingEmbeddingModel.java) | Deterministic 512-dimensional lexical feature vectors |
| [PolicyVectorIndex](../src/main/java/com/example/practice/knowledge/PolicyVectorIndex.java) | In-memory vectors, cosine ranking, relevance threshold and top-K |
| [KnowledgeService](../src/main/java/com/example/practice/knowledge/KnowledgeService.java) | Validates requests, bounds context, invokes model and attaches citations |
| [PolicyAnswerModel](../src/main/java/com/example/practice/knowledge/PolicyAnswerModel.java) | Swappable generation boundary |
| [DeterministicPolicyAnswerModel](../src/main/java/com/example/practice/knowledge/DeterministicPolicyAnswerModel.java) | No-key extractive baseline used for default/demo |
| [HttpPolicyAnswerModel](../src/main/java/com/example/practice/knowledge/HttpPolicyAnswerModel.java) | Optional OpenAI-compatible model call with explicit timeout/error behavior |
| [KnowledgeController](../src/main/java/com/example/practice/knowledge/KnowledgeController.java) | POST contract over the knowledge service |

Change a policy sentence and observe retrieval/citations. Try unrelated text and explain why generation is not called without evidence. Do not describe feature hashing as a pretrained semantic model or `grounded=true` as a proof of correctness.

## 8. Follow a model-facing tool

[OnboardingTools](../src/main/java/com/example/practice/mcp/OnboardingTools.java) exposes four read-only MCP operations. It validates UUIDs and paging limits, delegates to services, strips applicant fields and free-text history reasons, and translates failures into safe structured tool errors.

The Spring AI starter provides the actual stateless HTTP MCP protocol, tool discovery and schema handling. The handlers do not reimplement JSON-RPC or lifecycle logic. Tool annotations inform clients; the security filter and limited implementation enforce server-side boundaries.

Read `McpProtocolIntegrationTest` to see an actual initialize/list/call exchange, then compare REST `CaseResponse` with MCP `CaseSummary`.

## 9. Inspect cross-cutting behavior

| Class | Responsibility |
| --- | --- |
| [SecurityConfiguration](../src/main/java/com/example/practice/security/SecurityConfiguration.java) | Development operator/reader roles and consistent 401/403 responses |
| [ApiSecurityProperties](../src/main/java/com/example/practice/security/ApiSecurityProperties.java) | Validated environment-supplied credentials |
| [RequestLoggingFilter](../src/main/java/com/example/practice/observability/RequestLoggingFilter.java) | Safe correlation ID, completion logging and MDC cleanup |
| [OnboardingMetrics](../src/main/java/com/example/practice/observability/OnboardingMetrics.java) | Focused business/outbox signals |

Find which endpoints are public, reader-accessible and operator-only. Explain why stateless Basic is an explicit local demonstration and what OIDC/TLS/object authorization would add.

## 10. Read the tests before changing behavior

- `TransitionPolicyTest` and `OnboardingServiceTest` isolate rules/orchestration.
- `OnboardingApiIntegrationTest` exercises Spring HTTP/database contracts.
- `ReviewRecoveryIntegrationTest` proves the audited return-for-documents path.
- `PostgresIntegrationIT` checks actual PostgreSQL under the explicit profile.
- Screening tests control response sequences and timeout behavior.
- Event tests exercise database transactions, real broker delivery and replay/failure paths.
- Knowledge/MCP tests exercise retrieval, provider boundaries and the real protocol.
- `SecurityIntegrationTest` checks roles, safe endpoints and error behavior.

See [testing strategy](testing.md) for the precise distinction between these tests and `scripts/smoke_api.py`, which contacts a started application over TCP.

## 11. Build and deployment files

[Dockerfile](../Dockerfile) builds in a JDK stage and copies only the packaged app/health helper into a non-root JRE runtime. Optional BuildKit secrets support a managed Maven proxy without persisting its settings/trust store in image layers.

[docker-compose.yml](../docker-compose.yml) supplies PostgreSQL, a single Kafka broker, mock risk and application health gates. [create_env.py](../scripts/create_env.py) generates local ignored credentials without displaying them. [ci.yml](../.github/workflows/ci.yml) verifies Java tests, PostgreSQL and Compose configuration; it does not deploy.

For each file, explain the guarantee it actually provides. A healthy local Compose stack is useful evidence, but it is not an enterprise identity system, multi-region deployment, capacity plan or compliance certification.
