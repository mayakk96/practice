# Architecture and decisions

## One application, clear boundaries

This is a modular Spring Boot monolith. Packages separate onboarding, downstream screening, events, knowledge, MCP, security and common HTTP concerns. A single deployable application keeps the workflow explainable; Kafka demonstrates asynchronous integration without inventing multiple independently deployed business services.

```text
HTTP request -> security/filter -> OnboardingController -> OnboardingService
                                                        |
                                     TransitionPolicy / RiskScreeningClient
                                                        |
                                             JPA repositories -> database

Same database transaction: case change + history + outbox row
Later transaction: outbox dispatcher -> Kafka acknowledgement -> delivered marker
Later consumer transaction: unique event ID -> metadata audit row
```

Controllers translate HTTP into typed requests and response codes. Services enforce rules and transaction boundaries. Repositories express persistence queries. Entities model stored relationships; record DTOs define external contracts. The service calls a mapper while the persistence context is open, so DTO serialization does not accidentally lazy-load entities.

There is no generic base service, reflection mapper, custom dependency-injection framework, or unnecessary microservice boundary. Alternatives such as MapStruct, separate deployable services and CQRS would become useful only with demonstrated scale or maintenance needs.

## Relational model

| Table | Responsibility / constraints |
| --- | --- |
| `applicant` | Fictional applicant attributes; UUID primary key |
| `onboarding_case` | Applicant foreign key, state, risk, team, timestamps and JPA version |
| `case_document` | Case foreign key; unique `(case_id, document_type)`; metadata only |
| `status_history` | Case foreign key; previous/new state, reason and timestamp |
| `idempotency_request` | Unique request key, SHA-256 request fingerprint, resulting case foreign key |
| `event_outbox` | Durable, ordered event envelope and delivery attempts |
| `onboarding_audit_event` | Unique event UUID and non-personal audit metadata |

The outbox/audit case IDs are event references rather than foreign keys to an entity aggregate. This avoids coupling event retention to the current case lifecycle. State/document/risk check constraints protect the database against values outside the implemented enums. UUIDs make references stable across application/broker boundaries; they are not an authorization mechanism.

Flyway runs `V1__initial_schema.sql`, `V2__add_status_history.sql` and `V3__event_outbox_and_audit.sql`. Hibernate validates the resulting schema instead of silently modifying it. Do not edit an applied migration in a shared database: add the next version.

### Why these indexes exist

| Index / uniqueness | Query or invariant supported |
| --- | --- |
| `ix_case_applicant` | Cases for an applicant; foreign-key lookups |
| `ix_case_created(created_at, id)` | Stable paginated case ordering with a tie-breaker |
| `ix_case_status(status)` | Pending-state filtering for MCP/service queries |
| `uk_document_case_type(case_id, document_type)` | One document of each required type per case; approval lookup |
| `ix_history_case_time(case_id, changed_at, id)` | History for one case in deterministic order |
| `idempotency_request` primary key | Cross-instance duplicate request arbitration |
| `idx_outbox_pending` | Eligible unpublished events ordered by sequence |
| `idx_outbox_case_order` | Prevent later events overtaking earlier undelivered events for the same case |
| `onboarding_audit_event` primary key | Replay detection and one durable audit effect per event UUID |
| `idx_audit_case_time` | Audit records for a case ordered by event time |

Indexes cost storage and write work. These choices are query-informed teaching examples; a production decision also needs `EXPLAIN ANALYZE`, cardinality and observed query timings. Offset pagination is simple and bounded here; keyset pagination is an alternative for very large changing datasets.

## Explicit lifecycle policy

`TransitionPolicy` owns allowed state edges. Services add contextual requirements such as documents and risk decisions. Controllers do not scatter state comparisons.

```text
CREATED -> DOCUMENTS_PENDING -> UNDER_REVIEW -> APPROVED -> COMPLETED
                                      |
                                      +-> RISK_REVIEW -> APPROVED / REJECTED
                                      +-> REJECTED
```

Terminal cases cannot restart. `UNDER_REVIEW` and `RISK_REVIEW` can return to `DOCUMENTS_PENDING` with an audited reason; documents remain immutable while a case is in review. Approval needs both required document types and a usable screening result that is not high risk. Invalid transitions return `409` rather than an internal error. Transition history explains business changes; technical logs explain execution. Neither replaces the other.

## Transactions and concurrent requests

Creation atomically persists the applicant, case, initial history, idempotency claim when provided, and creation event. Status/document mutations lock the case row with `PESSIMISTIC_WRITE` so two writers cannot independently evaluate stale document/state rules. The entity also has `@Version` as a guard against stale updates.

Status change, history and event recording share one transaction. The outbox recorder requires an existing transaction; it cannot accidentally commit an event independently of the business update. A downstream exception propagates before the update commits, rolling back business/history/outbox changes together.

Screening is deliberately synchronous and bounded for study. Holding a row lock during a remote call increases contention and ties up a connection. A real long-running verification process would often persist a screening-requested state, release the transaction, call asynchronously, and apply the result using a version/state precondition. A saga or process manager can coordinate compensating actions; a database transaction cannot roll back a remote provider's side effects.

### Idempotency algorithm

1. Validate the optional header and normalize the request.
2. Fingerprint length-framed normalized fields with SHA-256.
3. In a new transaction, look up or insert-and-flush the unique request claim.
4. A new claim creates the aggregate and completes the claim in that transaction.
5. A matching existing claim returns the same case ID; a changed fingerprint returns `409`.
6. If two transactions race, the losing unique insert rolls back. Only then does the service read the committed winner in a fresh transaction.

Catching a uniqueness exception inside an already-aborted PostgreSQL transaction and continuing would be incorrect. An in-memory synchronized map would also fail across replicas. Tests exercise the real database claim path.

New claims implement Spring Data `Persistable` so an application-assigned key still causes `persist`/INSERT. With the default assigned-ID `save`/merge behavior, another request could commit between the initial lookup and merge's own lookup, allowing an existing claim to be overwritten. The claim and audit race tests pause at that exact boundary, commit a winner, and then resume the loser. Both matching replay and conflicting event metadata are checked.

The replay guarantee is **one created case per supplied key**, not a permanent byte-for-byte snapshot of the original HTTP response: replay returns the current representation of that case. Without a key, each valid POST can create a case. Keys are currently global and retained indefinitely; production should scope them to caller/operation, define expiry and response retention, and consider denial-of-service limits.

## External boundary

`RiskScreeningClient` is an application-facing port. The stub supports standalone/no-network study; the HTTP adapter owns protocol DTOs, headers, timeout configuration, response checks, retries and error translation. Business code sees a risk decision or a domain-specific exception, not a scattered collection of HTTP status checks.

Retries are bounded and use a stable downstream key. A timeout means the caller does not know whether the provider completed the request; provider-side idempotency is what makes a replay safe. A wrapper alone cannot guarantee the remote system implements that contract.

## Event boundary

Writing to Kafka and PostgreSQL separately creates a dual-write gap. The outbox makes the intent durable in the same database commit, then dispatches independently. Kafka broker acknowledgement and marking the database row delivered are still separate operations, so duplicates remain possible. The audit consumer has a database-unique event ID and an independent transaction boundary.

The case UUID is the partition key. Kafka orders records within a partition, while the outbox additionally prevents older events for a case being overtaken on retry. There is no global order across all cases. The versioned envelope excludes applicant names/email, document reference and free-text reason. Consumers retry transient failures and route exhausted/invalid records to a dead-letter topic.

## MCP and knowledge boundaries

MCP tools are a second inbound adapter over the same services. They accept bounded typed inputs and return reduced, read-only data. They do not bypass lifecycle rules or directly query/mutate repositories. Authentication at the transport and per-tool least privilege are separate from tool descriptions supplied to a model.

The RAG prototype keeps retrieval separate from generation. An embedding interface permits replacement of the local feature-hash baseline; an answer-model interface permits deterministic tests and optional HTTP generation. The in-memory vector index is suitable for a handful of bundled fictional policies. Retrieval scores are relevance signals, not factual confidence. See [AI/MCP notes](ai-mcp.md).

## Deployment boundary

Compose is a local learning topology: PostgreSQL plus one KRaft Kafka broker, the application and a mock provider. HTTP Basic is a development identity mechanism. The CI workflow compiles, tests and packages; it does not deploy or manage a production secret store.

Before claiming production readiness, address identity federation, object/tenant authorization, encrypted/authenticated infrastructure traffic, backups, capacity, retry/outbox retention, poison-event operations, schema compatibility, time budgets, alert thresholds and tested incident response.
