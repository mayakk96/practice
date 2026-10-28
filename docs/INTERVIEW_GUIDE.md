# Interview study guide

Use this guide with the source open. Practice explaining a real request, transaction and failure path, rather than reciting a technology list. This is a fictional educational project; describe it as personal portfolio work, never as software used by BNY, Discover or a real customer.

## 1. Java 21

**What:** An LTS Java release providing the language/runtime used by the project.

**Why here:** It gives a stable platform with records for small immutable DTOs and standard HTTP client support. The project uses ordinary synchronous Spring MVC/JPA, not a gratuitous concurrency rewrite.

**How here:** Request/response/event records carry explicit fields; enums constrain workflow vocabulary; UUIDs identify aggregates and events. Maven's release setting targets Java 21.

**Alternatives:** Java 17 for older estates, Kotlin for language preferences, virtual threads when measured blocking workloads justify them.

**Question:** “Why not use virtual threads everywhere?” **Answer:** “They can improve concurrency for blocking workloads, but they do not increase database capacity or remove lock contention. I would measure pool, thread and latency behavior first.”

**Follow-up:** Explain why more concurrent requests can overload a finite database pool.

## 2. Spring Boot and dependency injection

**What:** Boot supplies application startup, dependency management and conditional auto-configuration; DI constructs objects with their collaborators.

**Why here:** It removes repetitive server/JPA/serialization wiring while keeping application decisions explicit.

**How here:** `PracticeApplication` starts component scanning. Constructor parameters describe required dependencies. Configuration selects stub/HTTP screening, security mode, MCP transport and model adapter.

**Alternatives:** Manual composition, plain Spring, or another JVM framework. Field injection is less explicit and makes plain unit construction harder.

**Question:** “What does Boot auto-configure?” **Answer:** “Based on dependencies and properties, it configures infrastructure such as MVC, Jackson, JPA and Actuator. My service rules and transaction boundaries remain application code.”

**Follow-up:** Explain conditional beans and what happens when two beans match one interface.

## 3. Controller, service and repository layers

**What:** Separate HTTP adaptation, application workflow, and persistence.

**Why here:** The same service can support REST and MCP without duplicating business rules.

**How here:** `OnboardingController` delegates to `OnboardingService`; the service uses `TransitionPolicy` and repositories. MCP tools delegate to the same service.

**Alternatives:** A very small CRUD controller can call a repository directly. A richer system might use hexagonal ports or separate command/query models. Here the workflow justifies a service without a generic framework.

**Question:** “Where should an approval rule live?” **Answer:** “In the service/policy layer, because it must apply regardless of whether a request arrives through REST, MCP or another adapter.”

**Follow-up:** Distinguish entity-local invariants from workflow rules requiring multiple repositories.

## 4. DTOs, records and mapping

**What:** External request/response types distinct from persistence entities.

**Why here:** Entity fields, lazy relationships and database structure should not silently become public API contracts.

**How here:** `CreateCaseRequest` carries validation; `CaseResponse` is built by `OnboardingMapper`. MCP additionally reduces output to workflow metadata.

**Alternatives:** MapStruct can help with many mappings; manual mapping is easy to inspect at this size. Returning JPA entities is quick but couples serialization to persistence.

**Question:** “Why not return the entity?” **Answer:** “DTOs control exposed fields and avoid lazy-loading/cycle surprises. They let database relationships evolve independently of API representation.”

**Follow-up:** Explain how the MCP representation protects more information than the authenticated REST representation.

## 5. REST, HTTP verbs and status codes

**What:** Resource-oriented HTTP contracts with defined method semantics.

**Why here:** Callers need predictable behavior, retry decisions and machine-readable failures.

**How here:** POST creates cases/documents, GET reads cases/history, PATCH changes case status. Initial case creation returns 201/Location; replay returns 200; invalid input 400; missing case 404; business conflict 409.

**Alternatives:** PUT for a complete replacement, command endpoints for complex operations, GraphQL for client-shaped queries, messaging for asynchronous work.

**Question:** “Why PATCH for status?” **Answer:** “It changes one part of the case rather than replacing the full resource. The requested state is validated against an explicit transition policy.”

**Follow-up:** Distinguish GET's safe/idempotent semantics from POST with an application-level idempotency key.

## 6. Validation and exception handling

**What:** Reject malformed contracts and translate expected failures at a consistent boundary.

**Why here:** A database exception should not be a caller's first explanation of an invalid request.

**How here:** Jakarta constraints bound names, fictional email domains, team identifiers, reasons and document references. `GlobalExceptionHandler` returns Problem Details; security failures use the same general format.

**Alternatives:** Custom validators for cross-field contracts; service rules for state-dependent requirements. Validation cannot replace database constraints.

**Question:** “400 or 409?” **Answer:** “A malformed or invalid request contract is 400. A structurally valid request conflicting with current state or a reused idempotency key is 409.”

**Follow-up:** Explain why an approval requirement cannot be completely represented by `@NotNull`.

## 7. JPA, relationships and lazy loading

**What:** JPA maps objects to relational rows; Spring Data supplies repository implementations.

**Why here:** It supports relationship navigation and transactional aggregate updates without writing every CRUD statement.

**How here:** Cases reference applicants; document/history rows reference cases. Repository queries retrieve/lock cases, and DTO mapping happens inside service transactions.

**Alternatives:** JDBC/jOOQ for precise SQL control, or explicit query projections for read-heavy views.

**Question:** “What is the N+1 problem?” **Answer:** “Loading a page of cases can trigger one additional applicant query per case if relationships are lazily accessed. I inspect SQL and use fetch joins/entity graphs/projections for the actual query shape.”

**Follow-up:** Open `OnboardingCaseRepository` and identify which query handles applicant fetching and which locks a case.

## 8. PostgreSQL, constraints and indexes

**What:** A relational database with durable transactions, constraints and a query planner.

**Why here:** Cases, documents, history and idempotency have relationships and uniqueness requirements that belong in one transactional store.

**How here:** Flyway creates UUID PKs, FKs, enum checks and document uniqueness. Case-time, history-time and outbox indexes align to implemented queries.

**Alternatives:** Another relational engine is viable; a document store would require different consistency and relationship decisions.

**Question:** “Why index `case_id, changed_at, id`?” **Answer:** “History requests filter by case and return chronological records. The final ID makes ordering deterministic when timestamps tie.”

**Follow-up:** Discuss index selectivity, write overhead and validating a choice with `EXPLAIN ANALYZE`.

## 9. Transactions and locking

**What:** A transaction commits a consistent group of database changes or rolls them back.

**Why here:** A status update without history/outbox would leave incomplete business/audit state.

**How here:** Service mutations share transactions; creation uses `TransactionTemplate` to control rollback/recovery. Row locks serialize state/document checks; `@Version` also detects stale writes.

**Alternatives:** Optimistic-only retry, compare-and-set SQL, or an asynchronous process manager for long-lived external steps.

**Question:** “Does `@Transactional` roll back the external API?” **Answer:** “No. It governs the database transaction. A remote timeout may leave an unknown provider outcome, so the provider contract needs idempotency and reconciliation.”

**Follow-up:** Explain proxy-based transaction interception, self-invocation, isolation levels and connection-pool contention.

## 10. Flyway migrations

**What:** Versioned SQL applied and tracked in a database schema-history table.

**Why here:** Schema changes need reviewable, repeatable ordering rather than runtime guesswork.

**How here:** V1 creates domain/idempotency tables, V2 adds history, V3 adds outbox/audit. Hibernate validates mappings.

**Alternatives:** Liquibase, carefully managed plain SQL, or Hibernate generation for disposable prototypes only.

**Question:** “Why not `ddl-auto=update`?” **Answer:** “It does not provide the explicit versioned rollout history, review and operational control I want for a production-style schema.”

**Follow-up:** Discuss additive migrations, backfills and expand/contract deployment before dropping a column.

## 11. Unit tests, JUnit 5 and Mockito

**What:** Small tests isolate a rule or orchestration step; JUnit runs them and Mockito controls collaborators.

**Why here:** Illegal transitions and risk outcomes should be tested quickly and independently of a broker/database.

**How here:** Policy tests enumerate edges; service tests mock repositories, screening and events to assert decisions and collaborator effects.

**Alternatives:** Hand-written fakes, property-based tests for broader invariant exploration, or integration tests where framework behavior is essential.

**Question:** “What does a mocked repository not prove?” **Answer:** “It does not prove SQL, migrations, transaction interception, row locks or real uniqueness behavior. Those need database integration tests.”

**Follow-up:** Explain stubbing versus verification and avoid a test that only mirrors every line of the implementation.

## 12. Integration tests, MockMvc and Testcontainers

**What:** Tests exercise multiple real components together.

**Why here:** Controller contracts, migrations and database rollback can fail even when isolated methods pass.

**How here:** MockMvc runs Spring HTTP handling with H2/Flyway; `PostgresIntegrationIT` uses actual PostgreSQL through Testcontainers. Separate protocol tests use real HTTP for MCP.

**Alternatives:** A random-port HTTP test covers server transport; an end-to-end environment test covers more deployment boundaries at a higher cost.

**Question:** “Why H2 and PostgreSQL tests?” **Answer:** “H2 provides fast feedback, but compatibility mode is not the PostgreSQL engine. The separate PostgreSQL check validates actual dialect/constraint/concurrency behavior.”

**Follow-up:** Explain why a MockMvc test is not proof that a Docker port mapping works.

## 13. API wrappers

**What:** A reusable client translates an external protocol into an application-facing interface.

**Why here:** Business logic should not repeat base URLs, JSON, retry decisions and HTTP error handling.

**How here:** `RiskScreeningClient` exposes `screen(caseId)`. Its HTTP adapter implements headers, timeouts, serialization and sanitized exceptions; configuration can select a deterministic stub.

**Alternatives:** Generated OpenAPI clients, declarative clients or messaging. They still need application-specific error and idempotency decisions.

**Question:** “Why create a wrapper instead of calling HTTP everywhere?” **Answer:** “It centralizes the integration contract, makes failure handling consistent, and lets services/tests depend on a stable business interface.”

**Follow-up:** Distinguish a test stub from a production fallback that could incorrectly approve a case.

## 14. Timeouts, retries and exponential backoff

**What:** Timeouts bound waiting; retries repeat transient operations; exponential delays reduce synchronized pressure.

**Why here:** One unavailable provider should not consume threads/connections indefinitely or trigger uncontrolled retries.

**How here:** The screening adapter configures connect/read limits and capped attempts/backoff. It retries network failures, server errors and explicit throttling, while ordinary 4xx contract failures are not retried.

**Alternatives:** Circuit breakers, bulkheads, async queues, jitter and a total deadline. More resilience dependencies are useful only when their behavior is understood.

**Question:** “Why not retry every failure?” **Answer:** “A bad request stays bad, repeated calls amplify load, and a timed-out non-idempotent call may already have succeeded.”

**Follow-up:** Calculate the worst-case call budget, include backoff, and explain why nested retries can multiply attempts.

## 15. Idempotency

**What:** Repeating one logical request does not create additional business effects.

**Why here:** A client may retry after losing a successful response, especially in financial/distributed workflows.

**How here:** An optional key claims a normalized fingerprint in PostgreSQL. Matching replay returns the same case; changed payload conflicts. A unique insert loser rolls back, then reads the winner in a new transaction.

**Alternatives:** Natural business keys, conditional writes, stored original responses or provider-issued operation IDs.

**Question:** “Why not an in-memory map?” **Answer:** “It disappears on restart and cannot coordinate multiple instances. The database uniqueness constraint arbitrates concurrent requests.”

**Follow-up:** Discuss key scope, TTL, response snapshots, retry windows, and that this implementation returns the current case representation.

**Deeper follow-up:** “Why implement `Persistable` for a key we already assigned?” **Answer:** “Spring Data can interpret a non-null assigned ID as an existing entity and call merge. A concurrent winner could then be overwritten between two lookups. Our new claim and audit records explicitly report that they are new, forcing an INSERT so the database uniqueness constraint arbitrates the race. Deterministic tests pause immediately before persistence and commit the competing winner first.”

## 16. Distributed systems

**What:** Independent components communicate over unreliable boundaries and cannot share one ordinary local transaction.

**Why here:** The application database, Kafka broker and screening provider can fail independently.

**How here:** Timeouts/retries handle uncertainty, idempotency controls replays, and the outbox persists asynchronous intent. None makes the whole system one ACID transaction.

**Alternatives:** Distributed transactions in constrained settings, sagas/process managers, reconciliation and compensating operations.

**Question:** “What does a timeout mean?” **Answer:** “I know I did not receive a timely response; I do not know that the remote operation failed. Safe retry requires a contract for deduplication or reconciliation.”

**Follow-up:** Explain eventual consistency and user-visible status when downstream work is delayed.

## 17. Kafka topics, keys, partitions and consumer groups

**What:** Kafka stores ordered partition logs; consumer groups distribute partition processing.

**Why here:** Audit handling can occur after the synchronous request commits without coupling HTTP availability to immediate consumer execution.

**How here:** Versioned JSON envelopes go to `onboarding.events.v1`. The case UUID is the key, three partitions allow independent cases to progress, and the audit group reads events.

**Alternatives:** RabbitMQ, a database work queue, cloud messaging, or synchronous REST when immediate response coupling is intended.

**Question:** “What ordering do you guarantee?” **Answer:** “Kafka orders within a partition. Case keys keep a case's records together, and the outbox prevents earlier undelivered case events being overtaken. There is no global case order.”

**Follow-up:** Explain partition-count changes, rebalances, parallel consumers and schema compatibility.

## 18. Transactional outbox

**What:** Store an event intent in the same database transaction as the business change, then publish later.

**Why here:** Directly committing PostgreSQL and Kafka separately creates a dual-write loss window.

**How here:** `JpaDomainEventRecorder` requires an existing transaction. `OutboxDispatcher` invokes delivery, waits for broker acknowledgement and marks the row afterward.

**Alternatives:** Change-data-capture outbox, a transactional messaging platform, or a simpler database queue.

**Question:** “Is the outbox exactly once?” **Answer:** “No. A crash after Kafka acknowledgement but before the delivered marker can resend the record. I pair durable at-least-once delivery with idempotent consumption.”

**Follow-up:** Discuss backlog retention, delivery age, poison messages and multi-instance dispatch locking.

## 19. Duplicate events and failure handling

**What:** Consumers must tolerate replay and recover predictably from bad or transient records.

**Why here:** Broker redelivery and outbox crash windows are normal system behavior.

**How here:** `AuditEventService` uses a unique event UUID for one audit effect. Listener failures retry a bounded number of times; exhausted/invalid records go to `.DLT`.

**Alternatives:** Inbox tables, business-key upserts, idempotent projections, and manual reconciliation for non-repeatable side effects.

**Question:** “Why can a uniqueness exception be dangerous inside a transaction?” **Answer:** “PostgreSQL marks that transaction aborted. Recovery logic must roll it back and perform any follow-up lookup in a valid new transaction.”

**Follow-up:** Explain when an offset is committed, what happens if DLT publication fails, and how operators would replay a corrected record.

## 20. Maven and dependency management

**What:** Maven builds from a dependency/lifecycle model; the wrapper standardizes the launcher version.

**Why here:** A reviewer should build/test/package from one repository command.

**How here:** Boot manages compatible dependency versions, Surefire runs normal tests, Failsafe runs PostgreSQL ITs under a profile, and the Boot plugin creates an executable JAR.

**Alternatives:** Gradle or another build system. Reproducibility also needs pinned dependencies, trusted repositories and verified artifacts, not just a wrapper script.

**Question:** “What is the difference between test and verify?” **Answer:** “test reaches unit/test execution; verify reaches packaging and configured integration verification as well. Our PostgreSQL profile enables the Failsafe path.”

**Follow-up:** Explain dependency scopes and why an unused dependency increases maintenance/security surface.

## 21. Docker and Compose

**What:** Docker packages a process and dependencies; Compose describes a local multi-container topology.

**Why here:** Reviewers can run the app, PostgreSQL, Kafka and mock provider consistently.

**How here:** A multi-stage Dockerfile builds the JAR and runs it as a non-root user on a JRE. Compose configures services, health gates, environment credentials and loopback ports.

**Alternatives:** Local service installation, dev containers, or Kubernetes for an operationally justified deployment.

**Question:** “Does depends_on mean the API is ready?” **Answer:** “Only when configured health conditions cover the dependency. The application also needs a functional readiness request; a running container or open port alone is insufficient.”

**Follow-up:** Explain named-volume persistence, destructive `down -v`, image layers, and why secrets must not enter Docker layers.

## 22. CI/CD

**What:** CI automatically verifies changes; CD adds controlled delivery/deployment.

**Why here:** A portfolio should show repeatable checks for pushes/PRs rather than an unverified command list.

**How here:** GitHub Actions configures Java 21, runs Maven verification, PostgreSQL Testcontainers and Compose validation, then retains reports.

**Alternatives:** Other CI systems, separate build/test jobs, or reusable workflows as a project grows.

**Question:** “Where is deployment?” **Answer:** “This repository implements CI build/test/package, not a production deployment pipeline. Deployment would need a target, secrets, approvals and rollback strategy.”

**Follow-up:** Discuss artifact promotion versus rebuilding, least-privilege tokens, pinned action SHAs and dependency scanning.

## 23. Git workflow

**What:** Version control records coherent changes and supports review.

**Why here:** Reviewers need to understand why a feature changed, not sift through unrelated generated files.

**How here:** Source, tests, migrations and documentation are committed; local `.env`, database files and build output are ignored. Changes should use focused messages/stages.

**Alternatives:** Trunk-based development or short feature branches; both require small reviews and passing checks.

**Question:** “Does .gitignore remove an already committed secret?” **Answer:** “No. It prevents ordinary addition of matching untracked files. An exposed credential needs rotation and deliberate history/remediation, not only an ignore rule.”

**Follow-up:** Explain merge versus rebase and avoid rewriting shared history casually.

## 24. Observability, metrics and health

**What:** Metrics, logs and traces make system behavior diagnosable; health expresses availability conditions.

**Why here:** An API can accept work while asynchronous delivery falls behind.

**How here:** Actuator/Micrometer expose HTTP/JVM and focused workflow/integration signals. Readiness includes database availability; event backlog is a separate signal.

**Alternatives:** OpenTelemetry tracing, dedicated SLO dashboards and centralized alerting in a real deployment.

**Question:** “Which production signals matter first?” **Answer:** “Request volume/latency/error rate, database/pool health, screening failures, outbox age, consumer lag/DLT and business completion/rejection outcomes.”

**Follow-up:** Distinguish a counter from a gauge and liveness from readiness; avoid high-cardinality case IDs as metric tags.

## 25. Structured logging and correlation

**What:** Machine-readable logs with stable fields and a request ID.

**Why here:** A failure can be followed without parsing free-form text or logging personal data.

**How here:** ECS JSON console output and `RequestLoggingFilter` supply a safe request ID, response header and cleared MDC. Workflow logs contain IDs/statuses.

**Alternatives:** Tracing with spans/exporters, centralized log aggregation, or JSON formats aligned to another platform.

**Question:** “Why clear MDC?” **Answer:** “Servlet threads are reused. Without cleanup, a later request could inherit another request's correlation context.”

**Follow-up:** Explain why request IDs are not credentials, and why Authorization, email, document references and free-text reasons stay out of logs.

## 26. MCP tools versus resources

**What:** MCP is a protocol for model-connected applications. Tools are named invocations with input schemas; resources expose addressable context/data.

**Why here:** A model client can safely discover and invoke a small service-backed read surface.

**How here:** Spring AI's compatible MCP server exposes four read-only tools over stateless HTTP at `/mcp`. This repository does not add a separate MCP resources feature.

**Alternatives:** Direct REST tool definitions in one model client, MCP resources for URI-addressable context, or no model adapter.

**Question:** “Does readOnlyHint enforce security?” **Answer:** “No. It informs clients. The implementation exposes no mutation tools, validates input, sanitizes output, and relies on server-side authentication/authorization.”

**Follow-up:** Explain typed UUID/page/query validation, tool error results and avoiding personal fields in model context.

## 27. REST versus API wrapper versus MCP

**What:** REST is an HTTP resource interface; a wrapper is application-side client code; MCP is a model-facing interaction protocol.

**Why here:** They solve different boundaries rather than competing to replace one another.

**How here:** REST and MCP adapt inbound calls into services. The risk wrapper adapts an outbound provider protocol into a screening interface.

**Alternatives:** An API gateway may centralize routing/auth, but it does not replace application rules or a well-defined client contract.

**Question:** “Why doesn't MCP replace your service?” **Answer:** “Transport should not own approval, idempotency or transaction rules. Both REST and MCP should receive consistent behavior from the same application layer.”

**Follow-up:** Trace a tool call and identify where authentication, validation, business logic and persistence occur.

## 28. RAG pipeline

**What:** Retrieval-augmented generation selects relevant evidence before constructing a model prompt/answer.

**Why here:** A small fictional policy corpus supplies inspectable context instead of asking a model to invent onboarding policy.

**How here:** Loader -> overlapping chunks -> embeddings -> cosine index -> bounded context -> answer-model interface -> citations. Default generation is deterministic; optional HTTP mode calls a configured provider.

**Alternatives:** Keyword search, a trained embedding model/vector store, hybrid retrieval and reranking.

**Question:** “Why retrieve before generation?” **Answer:** “It supplies task-specific evidence within a bounded context and enables citations. It does not guarantee that every generated statement follows the evidence.”

**Follow-up:** Distinguish no relevant retrieval from an answer model ignoring otherwise good evidence.

## 29. Embeddings and retrieval quality

**What:** An embedding maps text into a numeric vector so similarity can rank candidates.

**Why here:** A local vector baseline makes the pipeline testable without an API key or large model download.

**How here:** `HashingEmbeddingModel` uses 512 signed feature-hash dimensions with normalization. `PolicyVectorIndex` scores cosine similarity and applies a relevance threshold.

**Alternatives:** A pretrained semantic embedding model captures meaning beyond token overlap; a persistent vector database supports larger corpora and filtering.

**Question:** “Are these semantic embeddings?” **Answer:** “No. They are a deterministic lexical feature-hash baseline with collisions and weak synonym handling. I label that limit explicitly.”

**Follow-up:** Explain cosine normalization, top-K/threshold tradeoffs, retrieval evaluation and why changing embedding models requires re-indexing.

## 30. Prompt and context management

**What:** Control what evidence and instructions reach a model, within a resource and trust budget.

**Why here:** Unlimited or untrusted context creates cost, latency, privacy and prompt-injection risks.

**How here:** Policies are fictional bundled files; chunks overlap; retrieval is capped; context is limited to 6000 characters. The model adapter treats evidence as data, and no answer can mutate a case.

**Alternatives:** Token-based budgets, source allowlists, retrieval ACLs, structured generation and independent answer evaluation.

**Question:** “Does grounded=true prove correctness?” **Answer:** “No. In this response it means supporting chunks were retrieved and supplied. A hosted generator can still hallucinate; citations and evaluation remain necessary.”

**Follow-up:** Explain why prompt text is not an authorization boundary and how document ACLs would need to flow into retrieval.

## 31. Security basics and production boundaries

**What:** Protect configuration/data and limit operations to authorized identities.

**Why here:** A financial-services interview should distinguish a controlled demo from actual enterprise security.

**How here:** Environment credentials, encoded in-memory passwords, stateless Basic roles, safe logging, fictional-data validation, loopback demo binding and read-only MCP.

**Alternatives:** OIDC/OAuth2 with a centralized identity provider, managed secret stores, TLS/mTLS, per-tenant authorization and policy engines where justified.

**Question:** “Would you deploy Basic auth like this in production?” **Answer:** “No. It is an explicit development mechanism. Production needs TLS, identity lifecycle, short-lived tokens, object-level authorization, audit/retention and operational controls.”

**Follow-up:** Discuss 401 versus 403, CSRF tradeoffs for a non-cookie API, credential rotation and dependency vulnerability response.

## What I must understand before showing this repository to an interviewer

- Trace one create request, one approval, one idempotency race and one event replay in the source.
- Explain which behavior is guaranteed by database constraints and which is merely checked in Java.
- Explain transaction rollback boundaries, including what cannot be rolled back at a remote provider.
- Demonstrate legal transitions, return-for-documents recovery, terminal states and missing-document rejection.
- Calculate the downstream retry/time budget and identify non-retryable failures.
- Describe the outbox crash window, ordering scope and consumer deduplication without an exactly-once claim.
- Identify which tests are unit, MockMvc integration, PostgreSQL, broker/protocol and real HTTP.
- Explain what H2 cannot prove about PostgreSQL.
- Show safe operator/reader behavior and the difference between tool hints and authorization.
- Explain the real feature-hash embedding and deterministic generator limits.
- Show the CI checks and distinguish them from deployment.
- Name concrete production gaps honestly; never imply the project was professional customer work.

## Ten repository-specific practice questions

1. Why does `OnboardingService.createCase` catch a uniqueness conflict outside its transaction?
2. What happens if a provider approves a request but the HTTP response times out?
3. How does the service prevent two concurrent mutations from evaluating different stale case states?
4. Which migration/index makes duplicate document types impossible?
5. Why can an outbox row be published twice, and what prevents two audit effects?
6. What ordering does the case UUID Kafka key provide, and what ordering does it not provide?
7. Which test would you run after changing PostgreSQL locking or migration SQL?
8. What information does the MCP case tool deliberately omit compared with the REST response?
9. What does the local embedding algorithm capture, and when will retrieval fail?
10. Which parts would you replace first before exposing this application to real users?

## Five live-coding exercises

1. Add a required `SOURCE_OF_FUNDS` document type: write a new migration, validation/rule changes and tests.
2. Add an audited `assignedTeam` reassignment endpoint with optimistic concurrency and reader/operator tests.
3. Add filtering by status to the paginated REST list and test invalid filters plus database ordering.
4. Add jitter and a total deadline to screening retries without retrying a 400 or changing the stable provider key.
5. Add a policy source filter to retrieval and MCP inputs, preserving context limits and citation correctness.
