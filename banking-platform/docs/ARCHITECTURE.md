# Architecture and consistency boundaries

The new application is a Python/FastAPI modular monolith with a React operations console. It does not invoke the separate Java onboarding project. One PostgreSQL database holds the banking write model, append-only financial history, outbox and reporting projection. Kafka transports domain events; the fictional HTTP network is a separate dependency.

## Components

| Boundary | Actual code | Responsibility |
| --- | --- | --- |
| HTTP / process wiring | `backend/app/main.py` | Request IDs, authentication/authorization, errors, router wiring and health |
| Transaction aggregate | `backend/app/transactions.py`, `models.py` | Submission, normalization, account rules, lifecycle, journals and history |
| Network adapter | `backend/app/network.py` | Stable downstream reference, response checks and bounded retry |
| Clearing | `backend/app/clearing.py` | Confirmation/import schema, row outcomes and duplicate detection |
| Settlement | `backend/app/settlement.py` | Batch membership, versions, totals and confirmation |
| Reconciliation / operations | `backend/app/reconciliation.py`, `exceptions.py` | Evidence snapshots, mismatch classifications, investigation audit |
| Events / read model | `backend/app/events.py`, `analytics.py` | Durable publication, deduplication, version-guarded projection, reporting |
| AI adapters | `backend/app/mcp_server.py`, `assistant.py`, `knowledge.py` | Read-only evidence access and bounded runbook retrieval |
| User interface | `frontend/src/` | Authenticated operations view using the same REST contracts |

## Transaction boundaries

A service receives a SQLAlchemy session factory and owns a transaction with `factory.begin()`. Controllers do not make partial commits. Creation atomically stores the idempotency claim, transaction, initial history and outbox events. A unique-claim race is handled only after rollback; a new transaction reads the committed winner and compares its normalized fingerprint. This matters on PostgreSQL because a failed unique insert aborts the transaction until rollback.

Capture atomically updates status/version, appends its paired journal and history, and records the outbox event. Clearing atomically inserts its confirmation and advances a captured transaction. Batch confirmation atomically checks its expected version, advances eligible transactions and creates settlement journals. A failure rolls back the whole command rather than leaving half a batch confirmed.

Reconciliation reads internal/external evidence for one currency and business date and persists an immutable result snapshot plus deduplicated work items. Exception edits use compare-and-set version semantics so a stale operator receives `409`. They do not change financial records.

## Concurrency controls

| Mechanism | Protected invariant | Why it exists |
| --- | --- | --- |
| Unique idempotency key and request hash | One financial transaction for one accepted instruction | Two processes can pass a pre-insert lookup simultaneously |
| Unique external reference | One internal identity per upstream business reference | A caller may accidentally choose a fresh idempotency key |
| `SELECT FOR UPDATE` on transactions | One lifecycle mutation at a time | Capture/reversal/settlement must see a consistent predecessor |
| Version check on operational/batch commands | A stale client cannot overwrite a newer decision | Holding an HTTP form does not hold a database lock |
| Unique settlement transaction membership | A transaction settles in one batch | Concurrent batch builders may select overlapping candidates |
| Unique original transaction on refund child | One full refund allocation | A fresh key must not create a second full refund |
| Consumer event ID + event fingerprint | One projection effect per event identity | Broker delivery can repeat and IDs can be misused |
| Projection aggregate version | An older event cannot regress current state | Replay and out-of-order transport need explicit policy |

SQLite does not implement PostgreSQL row locks; use PostgreSQL integration tests for concurrency claims. More application workers do not increase database capacity. A bounded connection pool, query plans and lock wait signals matter before adding concurrency.

## Synchronous and asynchronous paths

The HTTP path owns business mutations and a bounded network authorization call. It does not wait for Kafka analytics. The outbox row commits with business state; the dispatcher later sends it to Kafka. That separation avoids the unsafe “commit database then best-effort publish” gap but creates eventual consistency and backlog management.

The dispatcher publishes by aggregate key and records success only after broker acknowledgement. If it crashes after send and before recording delivery, the event is sent again. This is **at least once**, even with Kafka producer idempotence. Consumers commit their event receipt and read-model effect together and acknowledge only after success. Offsets alone do not make an external database effect exactly once.

Three keyed partitions give ordered delivery within each partition, not global ordering. Consumer groups distribute partitions; distinct groups independently receive the stream. Retained offsets allow restart/replay. Version guards prevent a stale state event replacing a newer snapshot. Dead-letter recovery retains poison evidence; it is an operational queue requiring diagnosis and controlled replay, not proof the business event was successfully applied.

## Database and index design

Alembic versions the schema; runtime startup does not call `create_all` to guess changes. Primary keys identify rows; foreign keys protect relationships; unique/check constraints protect invariants even if application code races. Major indexes serve transaction status/date/account-time queries, settlement batch lookups, reconciliation run/reference lookups, exception status queues, unpublished outbox scans and aggregate-version projection reads. Review the migration definitions alongside the actual filters and sorting; use `EXPLAIN (ANALYZE, BUFFERS)` on realistic PostgreSQL data before claiming an index is effective. Every index costs write/storage work.

Bounded pagination prevents unbounded API responses; deterministic final ID/sequence sorting handles tied timestamps. Current reconciliation intentionally bounds the educational run size rather than pretending it streams unlimited settlement files. A production implementation needs stable source cutoffs, partitioned imports and reproducible snapshots across independently changing sources.

Representative indexes and constraints have specific purposes:

| Index or unique key | Query/control it supports |
| --- | --- |
| Transaction external-reference uniqueness | Exact upstream-reference lookup and duplicate business-identity rejection |
| Idempotency request-key primary key | Claim insertion and fresh winner lookup after a unique race |
| `ix_tx_status_date` | Bounded eligible lifecycle/date populations, including settlement selection |
| `uq_tx_money` | The journal's composite foreign key to the transaction's full amount/currency |
| Transaction-history unique `(transaction_id, version)` | Ordered audit retrieval and one transition record per aggregate version |
| Journal unique `(transaction_id, event_type)` | One capture/reversal/settlement journal per financial event |
| Clearing import hash and `(import_id, row_number)` uniqueness | Duplicate-file identity and deterministic row-audit retrieval |
| Settlement-item transaction uniqueness | Final guard against concurrent double batch membership |
| `ix_settlement_items_batch` | Bounded batch item lookup during inspection/confirmation |
| `ix_external_recon_date_currency_ref` and `ix_external_recon_reference` | Date/currency evidence population plus reference-based anomaly lookup |
| Reconciliation-result unique `(run_id, external_reference)` | One snapshot comparison per reference and paginated run inspection |
| `ix_exception_status_created` | Status-filtered operational work queue with stable ordering |
| `ix_banking_outbox_pending` | Eligible unpublished dispatch scan |
| `ix_banking_outbox_order` | Detect earlier unpublished events of the same aggregate before sending |
| `ix_banking_projection_daily` | Currency/date/status reporting population |

Unique constraints already create usable PostgreSQL B-tree indexes; adding an identical nonunique index would duplicate write/storage cost. The guide describes query intent, not a measured speedup. Query plans under realistic data determine whether an index should be retained or changed.

## Failure and security behavior

Network retries are limited to configured transient statuses/transport failures; permanent 4xx failures are not blindly repeated. The stable transaction UUID becomes the provider idempotency reference. A timeout means “unknown remote outcome,” not “the provider did nothing.” Synchronous calls can hold a row lock during the bounded retry budget; a real long-running provider flow would use a durable process manager and lookup/reconciliation.

Errors are Problem Details with request IDs, without SQL, stack traces or provider bodies. JSON logs include safe identifiers and timings. HTTP Basic demonstrates operator/reader boundaries; it is not a substitute for enterprise identity, TLS, fine-grained resource authorization or financial approval workflows. MCP methods contain no financial mutation operations. Retrieved runbooks and model text remain untrusted evidence.

## Tradeoffs

SQLAlchemy retains explicit SQL concepts while keeping portable tests. PostgreSQL proves constraints/locking; SQLite lowers the barrier to a local demonstration. One database makes financial invariants and outbox atomicity inspectable. Kafka adds meaningful eventual read-model processing rather than splitting the application into artificial microservices. Paired journals simplify balanced two-leg postings at the cost of multi-leg accounting flexibility. Hypothetical production designs live in separate clearly labeled documents.
