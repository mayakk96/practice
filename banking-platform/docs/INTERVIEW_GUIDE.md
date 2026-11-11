# Interview guide: explain the code and its limits

This is independent synthetic portfolio work. Answer with the actual Python/JavaScript implementation open. Distinguish implemented controls from production proposals; do not imply employer affiliation or real deployment. The aggressive follow-ups are intended to test boundaries, not encourage unsupported guarantees.

## Banking domain and financial controls

### 1. Walk one transaction from receipt through reconciliation.

An API validates a synthetic instruction and atomically stores its idempotency claim, transaction, history and outbox. Authorization obtains a bounded network decision; capture posts a balanced journal; clearing confirms details; settlement batches eligible records. Reconciliation then compares independent external evidence and creates work items for discrepancies. Each step has a different business meaning and failure boundary.

**Follow-up:** Open transactions.py, settlement.py and reconciliation.py. Which actions share a database commit, and which require later evidence?

### 2. How do authorization, clearing and settlement differ?

Authorization accepts a proposal, clearing confirms the details to be exchanged, and settlement confirms the batch's financial movement. An authorization is not proof that cash moved. This project models those stages explicitly but does not connect to real settlement rails or implement issuer holds.

**Follow-up:** If authorization succeeded but clearing never arrived, which status and operational evidence would you expect?

### 3. Why is capture separate from authorization?

A proposal may be accepted before the merchant or originating workflow finalizes its amount for processing. Capture records the financial event and creates the journal in this model. Keeping the stages separate prevents an accepted-but-cancelled proposal from being treated as a settled payment.

**Follow-up:** Why must a declined authorization never reach capture? Where is that rule enforced?

### 4. What is reconciliation proving?

It proves whether the selected internal and independently received external records agree under defined matching rules. It is not a substitute for ledger balancing: two balanced systems can disagree with each other. A run needs a reproducible population, currency, business date, source identities, totals and detailed results.

**Follow-up:** Could two incorrect records match? Explain why reconciliation does not prove economic legitimacy.

### 5. What causes a settlement variance?

Missing records, duplicate evidence, amount differences, incorrect directions, timing and currency classification can change a net total. Investigate the contributing references rather than posting a blind balancing adjustment. The engine stores record-level classifications and signed totals so an operator can explain a USD50 difference instead of merely observing it.

**Follow-up:** If the total variance is zero, can there still be serious mismatches? Give two offsetting errors.

### 6. Why is a reversal different from a refund?

A reversal cancels an authorized or captured payment before clearing; a captured reversal appends compensation. A refund follows settlement and is a new linked transaction with the opposite economic direction and its own lifecycle. The project supports one full refund child, enforced by a unique original-transaction link.

**Follow-up:** Why would editing the original amount to zero destroy useful evidence?

### 7. What makes a double-entry journal balanced?

Debits and credits are equal in the same currency for the financial event. This implementation represents the common two-leg journal as one amount and paired accounts, exposing both postings through a view. A valid journal is not proof that the chosen account or transaction was correct; account-purpose rules and reconciliation still matter.

**Follow-up:** Can a perfectly balanced fraud transaction exist? Which other controls are needed?

### 8. Why avoid a mutable balance as the only record?

A single balance cannot explain when, why or by whom money changed. Append-only journals preserve the sequence of economic events and compensating corrections. A spendable balance additionally requires opening balances, holds, pending activity and funding policy, which this project deliberately does not claim to implement.

**Follow-up:** How would you reconstruct an as-of balance without losing effective-date semantics?

### 9. How do business dates differ from timestamps?

A UTC timestamp identifies an instant; a business date identifies the accounting or settlement population. A payment after a local cutoff may belong to another business date. This project requires explicit dates and does not infer a banking calendar from the host timezone; real holidays/cutoffs are a documented extension.

**Follow-up:** What happens when two regions have different holiday calendars?

### 10. Why are duplicate instructions dangerous?

A duplicated business instruction can create a second obligation even when both individual transactions are internally valid and balanced. Idempotency keys protect submission identity; unique external references add an independent upstream business control. Neither permits silently discarding distinct legitimate transactions just because their amounts match.

**Follow-up:** Why is a hash of amount and account alone an unsafe deduplication identity?

### 11. Does resolving an exception fix the payment?

No. Resolution records an operator's investigation outcome and notes. Reconciliation snapshots and journals remain unchanged. A legitimate financial correction needs an authorized business command and new audit history, followed by fresh reconciliation evidence.

**Follow-up:** What evidence would justify closure if the external file was corrected later?

### 12. Why constrain the educational transaction types?

A coherent subset makes financial rules and tests inspectable. CARD_PURCHASE and ACCOUNT_TRANSFER share a simplified outbound accounting model; full REFUND uses an opposite direction. The application does not pretend to implement all ACH timing, fees, disputes, FX and card-network rules simply by adding enum names.

**Follow-up:** What additional rules would a partial refund require beyond adding a field?

## Python and application design

### 13. Why use dataclasses or typed DTOs?

A typed request/response defines the contract independently of the ORM representation. Frozen dataclasses are useful for values such as a network decision; Pydantic validates inbound data and aliases camelCase fields. Type annotations improve tooling but do not replace runtime validation at untrusted boundaries.

**Follow-up:** Can a typed Python function still receive a wrong type at runtime?

### 14. Why does the API require strict integer money?

Python integers do not have binary floating-point rounding, but bool is an int subclass and permissive coercion can accept unexpected input. Strict validation rejects floats, strings and booleans for financial amounts. Database checks provide another boundary, and supported amount/currency ranges remain explicit.

**Follow-up:** What would int(10.99) do, and why must a payment API avoid that coercion?

### 15. What is the difference between identity and equality?

Identity means two references point to the same object; equality means values compare according to a defined rule. Database UUID identity should not be confused with an ORM instance's in-process identity. Never use Python object identity as a durable transaction or deduplication key.

**Follow-up:** Why can two ORM sessions load different Python objects for the same database row?

### 16. When are dictionaries useful and dangerous?

Dictionaries make small structured outputs and lookup maps clear, such as reconciliation candidates keyed by external reference. Missing or misspelled keys and accidental overwrites can hide business defects. Group duplicates into lists rather than overwriting them while building a reconciliation map.

**Follow-up:** How would dict[reference] = row conceal duplicate external records?

### 17. What does an immutable value help protect?

It prevents callers from changing a shared decision after validation and makes reasoning about a computation easier. An immutable Python object does not make its persisted database record immutable or authorize its contents. Financial immutability also requires API boundaries, permissions and database controls.

**Follow-up:** Can a frozen dataclass contain a mutable list?

### 18. Why use context managers for sessions?

A session/transaction context guarantees cleanup and establishes where commit or rollback happens. Service functions should return serialized data while their session is valid instead of leaking lazy ORM instances into HTTP serialization. Cleanup is especially important when a network or database operation raises.

**Follow-up:** What state is a SQLAlchemy session in after an IntegrityError until rollback?

### 19. Why should exception handling be narrow?

Expected domain conflicts need predictable status codes; programming errors need safe failure and diagnosis. Catching every exception and returning success hides defects and can commit incomplete work. At the HTTP boundary an unexpected error is sanitized, while internal logs retain safe classification and correlation metadata.

**Follow-up:** Why should a duplicate-key recovery not treat every integrity error as a replay?

### 20. How do generators differ from lists?

A generator yields lazily while a list materializes all values. Streaming can reduce memory, but it changes session lifetime, retry and snapshot semantics. A reconciliation engine must not claim bounded memory merely because one helper uses a generator while all database rows are still loaded elsewhere.

**Follow-up:** What happens if an exception occurs halfway through a streamed HTTP response?

### 21. Does async make blocking work faster?

Async permits concurrency when code awaits nonblocking I/O; it does not reduce a provider's latency or make blocking SQLAlchemy/HTTP work nonblocking. Sync FastAPI handlers are a reasonable choice for this bounded blocking stack. Mixing blocking calls into an event-loop handler can stall unrelated requests.

**Follow-up:** How would you measure whether thread capacity or database contention limits this service?

### 22. Does the GIL protect financial correctness?

No. The GIL is an interpreter execution property, not a cross-process database invariant. Multiple workers and service instances can race, and I/O releases execution opportunities. Unique constraints, transaction isolation, row locks and compare-and-set versions protect durable state.

**Follow-up:** Why would a threading.Lock fail when running two API containers?

### 23. Why inject a session factory or network client?

Explicit collaborators make transaction orchestration and failure tests controllable without global monkeypatching. A service still uses the same policy regardless of REST or MCP entry point. Injection is useful at real boundaries; a generic abstraction for every helper would obscure rather than improve this project.

**Follow-up:** Which tests require a real database despite injecting a factory?

### 24. How do you prevent module import cycles?

Keep shared models/errors/helpers in stable modules, avoid constructing services while importing peer modules, and use local imports at genuine integration points when necessary. A circular dependency can reveal unclear responsibility boundaries. Merely moving all code into one file avoids an import error but loses the modular design.

**Follow-up:** Where do transition helpers and event recording meet in this codebase?

## FastAPI, SQLAlchemy and transaction orchestration

### 25. What belongs in a controller?

HTTP adapters parse validated input, select response status/headers and delegate to services. Business rules, database transaction boundaries and state-machine decisions belong below the controller so scripts, jobs and read-only tools reuse the same behavior. Directly exposing ORM repositories would bypass these controls.

**Follow-up:** Where would a new rule requiring an active account be added and tested?

### 26. What does Pydantic validation not prove?

It proves input shape and declared field constraints, not that an account exists, has the correct currency or is eligible at the time of commit. State-dependent checks belong in the service transaction. Database foreign keys and checks protect another layer under concurrent access.

**Follow-up:** Could an account become inactive after the request body was validated?

### 27. Why is the service transaction important?

Status, journal, history and outbox must either all commit or all roll back. Committing inside small helpers can leave a captured transaction without its financial or audit evidence. Helpers should join the caller's session rather than quietly owning independent commits.

**Follow-up:** Show a failure after ledger insertion and explain the expected persisted state.

### 28. Why must replay recovery start after rollback?

A PostgreSQL unique violation aborts the current transaction, and SQLAlchemy marks the session failed. Querying the winner inside that transaction is invalid. The service exits/rolls back, opens a fresh transaction, loads the committed claim and compares the fingerprint before returning a replay.

**Follow-up:** What if the integrity error came from a missing foreign key instead of the idempotency claim?

### 29. What is optimistic concurrency?

The client or ORM supplies the version it read, and an update succeeds only if that version remains current. A zero-row compare-and-set update becomes a conflict rather than overwriting another analyst. It works well for forms and low-contention edits without holding a database lock while a user thinks.

**Follow-up:** Why must checking version and writing happen atomically rather than as two unrelated statements?

### 30. When is pessimistic locking justified?

A transaction row lock serializes conflicting lifecycle commands that must inspect current state and create one financial effect. It is short-lived database coordination, not a global system lock. Remote calls inside that lock have an explicit bounded budget but remain a documented scalability tradeoff.

**Follow-up:** What lock ordering would you choose when a command touches parent and refund child?

### 31. Why keep ORM objects inside the session boundary?

Lazy attributes can issue queries after the session has closed or during response serialization, causing errors or unexpected SQL. Returning explicit dictionaries/DTOs makes the API shape and transaction lifetime clear. It also helps prevent accidentally publishing account/customer fields through MCP.

**Follow-up:** How would you detect an N+1 query problem on a list endpoint?

### 32. What is the N+1 query problem?

One query loads a page and another query per row loads related data, multiplying database work. Explicit joins, eager loading or projections should match the response needs. Optimizing requires observing query counts and plans rather than assuming every ORM relationship is free.

**Follow-up:** Why can eager loading every relationship also be harmful?

### 33. Why migrate instead of create_all at startup?

Versioned Alembic migrations are reviewable schema changes with an ordered history. Runtime schema guessing can conceal drift and cannot express careful backfills or rollout sequencing. The application can validate/use a migrated schema without granting every process DDL privileges.

**Follow-up:** How would you add a required column without breaking old application instances?

### 34. What does dependency injection not solve?

It does not create distributed atomicity, fix a poor transaction boundary or make a mocked database equivalent to PostgreSQL. It clarifies composition and test control. The project keeps business state atomic within its database and handles the network/Kafka boundaries explicitly.

**Follow-up:** Why can a perfectly unit-tested orchestration still fail under a real unique-key race?

## PostgreSQL, isolation, constraints and query plans

### 35. Why PostgreSQL rather than only SQLite?

The production-like model relies on row locks, transaction isolation, unique-key races and PostgreSQL semantics. SQLite is valuable for a low-friction demo but serializes writes differently and ignores PostgreSQL FOR UPDATE behavior. Concurrency claims require actual PostgreSQL tests.

**Follow-up:** Which green SQLite test would fail to prove concurrent settlement safety?

### 36. What does READ COMMITTED mean?

Each statement sees data committed before that statement starts, plus its own changes. Two statements in one transaction can observe different committed worlds. Row locks and unique constraints still matter, and a multi-statement reconciliation snapshot needs a defined isolation/source-cutoff policy.

**Follow-up:** Could rows arriving during a run change which records are compared? How would production fix the cutoff?

### 37. What is a lost update?

Two clients read the same old value, then each writes a result derived from it; the later write silently erases the earlier decision. A version predicate or row lock prevents this for exception/batch commands. A Java/Python precheck without an atomic database write is insufficient.

**Follow-up:** Why is SET version=version+1 alone not a stale-client check?

### 38. How do unique constraints help idempotency?

They make the database arbitrate simultaneous claims across all processes. A preliminary lookup can improve the common replay path but cannot guarantee uniqueness by itself. The losing insert rolls back and then reads/validates the winner rather than creating another transaction.

**Follow-up:** What happens if two keys carry the same external business reference?

### 39. Why use foreign keys?

They prevent orphaned financial relationships even when application code is wrong or concurrent. A settlement item must reference a real transaction/batch, and a refund must link to an existing original. Foreign keys do not by themselves prove the referenced row has the right currency or business state.

**Follow-up:** Can a foreign key ensure a transaction is CLEARED before settlement membership?

### 40. What are check constraints good for?

They enforce row-local invariants such as positive bounded money, allowed currency, valid status and distinct debit/credit accounts. They are an independent safety boundary under direct SQL or application bugs. Cross-row sums generally need a different design; the paired journal avoids an unbalanced multi-row commit structurally.

**Follow-up:** Why is a naive CHECK over SUM(other rows) not a normal row constraint?

### 41. How do you choose a composite index?

Start from a real filter and ordering pattern, such as status plus business date plus deterministic ID. Column order affects which predicates and sorts the index can support. Validate representative data with EXPLAIN rather than indexing every field and paying unmeasured write costs.

**Follow-up:** What happens when a status filter matches most of the table?

### 42. What does EXPLAIN ANALYZE reveal?

It executes the query and reports actual timing/row counts alongside the plan. Comparing estimated versus actual rows helps identify selectivity/statistics errors, scans and join costs. On a production write query it can have real effects, so use safe transactions or representative nonproduction data.

**Follow-up:** Why might a sequential scan be faster than an index scan?

### 43. What is a deadlock?

Two transactions hold locks each other needs, so neither can progress. PostgreSQL detects a cycle and aborts a victim. Consistent lock ordering, bounded work and carefully scoped retry of the entire transaction reduce the risk; retrying only the last statement can violate business assumptions.

**Follow-up:** If transaction IDs are locked in different orders by two batch builders, what would you change?

### 44. How do you prevent a transaction entering two batches?

A unique settlement-item transaction ID is the final invariant. Selection/locking reduces contention, but an optimistic race must still fail safely at insertion/commit. The losing batch creation should roll back completely rather than retaining misleading totals with missing items.

**Follow-up:** Why is WHERE NOT EXISTS in the selection query insufficient alone?

### 45. What does an index cost?

It consumes storage, adds work to inserts/updates/deletes and can increase vacuum and cache pressure. A useful index reduces reads for a defined workload; unused or redundant indexes can harm a write-heavy payment path. Query patterns and measured plans determine whether it earns its cost.

**Follow-up:** Would an index on every enum always improve this system?

### 46. How would you evolve the schema safely?

Use expand/contract: add compatible structure, deploy code that handles both forms, backfill in bounded batches, validate constraints and only then remove old structure. Plan lock duration and rollback/forward recovery. Alembic migration success on an empty test database does not prove a large-table production rollout is safe.

**Follow-up:** What is the danger of adding a non-null column with an expensive default to a large table?

## Kafka and the analytics data pipeline

### 47. What ordering does a Kafka key provide?

The same key maps to one partition under a stable partitioning scheme, so that partition preserves append order. It does not order different partitions globally or repair events published in the wrong sequence. The dispatcher and aggregate versions contribute additional safeguards.

**Follow-up:** What changes if the topic's partition count increases?

### 48. What is a consumer group?

A group coordinates consumers so each partition is assigned to one active member in that group. Another group can independently process the same topic. More consumers than partitions do not increase parallel partition processing, and rebalances can cause replay around commit boundaries.

**Follow-up:** Why might audit and analytics use distinct groups?

### 49. What is an offset?

It identifies a position within a partition, not a global event sequence or business transaction ID. Committing an offset records consumer progress. A database effect can commit before its offset, leaving a replay window that requires business deduplication.

**Follow-up:** Why does committing the offset before the database effect risk data loss?

### 50. Why is the outbox at least once?

The database commits the business state and event together. A dispatcher can publish successfully then crash before recording delivery, so it later resends. Kafka producer idempotence does not make the external PostgreSQL delivered marker and broker append one atomic transaction.

**Follow-up:** Draw the crash window and identify exactly which effect repeats.

### 51. How does consumer deduplication work?

The consumer inserts a unique event ID and fingerprint in the same database transaction as its projection update. A replay with the same identity/content becomes a no-op; reused identity with altered content is rejected. Race recovery occurs after rollback before reading the winner.

**Follow-up:** Why must the receipt and projection update commit together?

### 52. Why guard projection versions?

A replay or out-of-order state event must not regress a newer transaction snapshot to an earlier state. The projection condition applies only a strictly newer aggregate version. This policy suits latest-state projections; an accounting event stream that accumulates deltas needs a different gap/ordering design.

**Follow-up:** Could ignoring an older delta lose money even if version guarding is correct for snapshots?

### 53. How do you rebuild a read model?

Preserve the financial source, stop the affected consumer, clear only its projection and matching dedup receipts, reset its offsets to retained history, then replay and validate totals. Clearing projection alone while leaving receipts prevents old events from being reapplied. Missing retained events require a source snapshot/backfill strategy.

**Follow-up:** What if retention expired before the earliest required event?

### 54. What belongs in a dead-letter topic?

A record that cannot be applied after the configured retry policy, plus safe metadata sufficient to diagnose it. DLT publication must be acknowledged before treating recovery as complete. A DLT is not business success; operators must monitor, repair the cause and replay deliberately.

**Follow-up:** What if DLT publication fails too?

### 55. What is consumer lag?

It is the distance between a group's committed position and broker end offsets, usually per partition. It helps detect delayed consumption but does not alone measure end-to-end event age or prove business effects are correct. This project does not claim a production lag collector merely because Kafka is present.

**Follow-up:** Can lag be zero while the projection is wrong?

### 56. Why separate reporting from the write model?

Reporting queries and eventual aggregate views should not complicate or slow the critical transaction path unnecessarily. The projection can be rebuilt and exposes its source/lag limitations. PostgreSQL can host both logical models without introducing another database solely for a technology list.

**Follow-up:** Which dashboard facts may be stale, and how should an operator know?

### 57. What is a poison event?

It is a record that repeatedly fails due to schema, validation or application assumptions rather than a transient outage. Infinite retry can block a partition and all later keyed traffic. Classify permanent failures, retain evidence and use controlled DLT/replay behavior.

**Follow-up:** Would retrying malformed JSON three thousand times make it valid?

### 58. How do event schemas evolve?

Version envelopes and favor compatible additions with explicit consumer validation. Producers and consumers may deploy independently, so removing or reinterpreting fields needs migration and replay planning. A schema version integer without an actual compatibility policy is only metadata.

**Follow-up:** How would an old consumer process a new status value?

## Distributed systems and resilience

### 59. What does a timeout prove?

Only that the caller did not obtain a usable response within its budget. The remote system may have rejected, accepted or completed the action. Stable downstream idempotency references and lookup/reconciliation address that ambiguity; generating a fresh reference can duplicate a financial decision.

**Follow-up:** The provider says it processed the request after your timeout. What local state should you inspect?

### 60. Which failures should be retried?

Retry only failures plausibly transient under the provider contract, such as selected5xx,429 or transport errors. Bound attempts and delays and preserve the same business identity.400,401,403 and deterministic validation failures usually need a corrected request or configuration rather than repetition.

**Follow-up:** Why is409 business-specific rather than universally retryable?

### 61. Why exponential backoff?

Increasing delays reduce repeated pressure during a dependency failure. Jitter can prevent synchronized clients from retrying together, and a total deadline bounds user-visible time. This project's bounded retry is explicit; do not claim jitter or a strict global deadline unless the code implements it.

**Follow-up:** How can retries triple an overloaded provider's traffic?

### 62. What does Retry-After mean?

It suggests when to retry, as seconds or an HTTP date. Parse it safely, cap the delay against local budgets and avoid trusting an unbounded remote value. A caller may decide to fail quickly rather than sleep beyond its allowed request duration.

**Follow-up:** What if the header asks you to wait one day?

### 63. Why not wrap HTTP in a database transaction and call it atomic?

A local database rollback cannot undo a remote system's committed action. The transaction can atomically preserve local state/history/outbox, but the network boundary remains a partial-failure problem. Idempotency, durable workflow state and reconciliation bridge that boundary.

**Follow-up:** What happens when a network decision succeeds but the local database commit fails?

### 64. What is a saga?

A saga coordinates multiple committed steps with explicit compensating actions instead of one cross-system transaction. Compensation is a new business event, not a rollback of history. This project models reversal/refund concepts but does not claim a full distributed saga engine.

**Follow-up:** Why might a refund fail even after the original payment succeeded?

### 65. What does CAP say here?

During a network partition, a distributed system cannot guarantee both linearizable consistency and availability for all operations. It is not a rule that every database randomly chooses two letters. Financial commands often favor rejecting/deferring uncertain writes while reporting can tolerate eventual consistency.

**Follow-up:** Would you accept competing full-refund writes in two isolated regions?

### 66. What is a circuit breaker?

It stops calls temporarily after a configured failure pattern and probes recovery later. It can reduce pressure but adds state, tuning and failure modes. The project does not need a homegrown breaker to demonstrate bounded retries; a production addition should use a standard implementation and tests.

**Follow-up:** How would half-open probes behave across many API replicas?

### 67. What is a bulkhead?

It limits one dependency or workload's use of shared capacity, preventing its failure from consuming every worker/connection. Thread pools, semaphores and separate connection pools can implement capacity boundaries. A limit must also define queueing, timeout and rejection behavior.

**Follow-up:** Why can adding threads worsen database saturation?

### 68. What is backpressure?

It prevents upstream production from permanently outrunning downstream capacity. A queue can absorb a burst but cannot solve an infinite rate mismatch. Outbox backlog age, admission limits, consumer capacity and explicit failure responses are part of a sustainable design.

**Follow-up:** What would you do when the oldest pending event grows every hour?

### 69. What is the difference between availability and correctness?

A fast200 response can still represent duplicate or inconsistent financial processing. Availability measures successful service under a defined contract; correctness requires invariant and evidence checks. Returning success without durable state simply to improve an SLI is misleading.

**Follow-up:** How would a business error affect a request-based availability SLI?

### 70. Why avoid exactly-once claims?

The system crosses PostgreSQL, HTTP and Kafka boundaries with independent commits. Deduplication can make specific side effects idempotent under stated identities, but it does not create universal exactly-once delivery. Describe each scope and crash window precisely.

**Follow-up:** Which guarantees would Kafka transactions improve, and which external database gap remains?

## REST and API contracts

### 71. When should creation return201 or200?

A new transaction returns 201 with its identity/location; an identical idempotency replay returns200 and the original result. The replay is a business contract, not HTTP's default behavior for arbitrary POSTs. A reused key with a different normalized request returns409.

**Follow-up:** Should the response reveal whether the request was replayed? Why?

### 72. What distinguishes400,409 and422?

Malformed request shape or syntax is invalid input; a valid command conflicting with current state is409. FastAPI commonly uses422 for field-validation failures unless the application normalizes them. Use the actual documented handler behavior rather than choosing codes randomly across endpoints.

**Follow-up:** Why is CAPTURED→AUTHORIZED a state conflict rather than a server500?

### 73. Why Problem Details?

It gives clients a consistent machine-readable error shape with status, title/detail and requestId while protecting internal SQL/stack/provider data. Clients should use status/contracts rather than parse human prose. Security middleware errors should follow the same general privacy boundary.

**Follow-up:** What information would you retain internally without returning it publicly?

### 74. What does idempotent mean?

Repeating an operation has the same intended effect as performing it once. It does not require identical transport status every time, and a read can remain safe while its output changes as the world changes. Submission idempotency uses an explicit business key and normalized request identity.

**Follow-up:** Can a POST be application-idempotent without becoming a PUT?

### 75. Why bound pagination?

It bounds database/serialization work and prevents a caller accidentally requesting the entire financial history. Deterministic sorting makes pages interpretable when timestamps tie. Offset pagination is simple but can shift under inserts; cursor pagination is a production extension for stable large feeds.

**Follow-up:** What happens to page2 when new records are inserted before page1?

### 76. Why validate unknown fields?

Silently ignoring a misspelled amount or business-date field can create surprising financial instructions. Rejecting extra fields makes contract mistakes visible. Backward compatibility still requires deliberate API evolution rather than globally accepting arbitrary input.

**Follow-up:** How would you add an optional field without breaking existing clients?

### 77. What should an API client wrapper own?

It owns transport serialization, base URL, timeouts, headers, response validation, retry decisions and safe error translation. Domain services depend on a small decision interface, not raw provider response bodies. Stable references and correlation headers must survive every attempt.

**Follow-up:** Why should the transaction controller not implement HTTP retry loops?

### 78. Why keep correlation IDs bounded?

A caller-controlled ID can become log injection or high-cardinality garbage if unvalidated. Generate or accept a safe bounded value, return it and propagate it to dependencies. It helps connect evidence but is not authorization or a durable transaction identifier.

**Follow-up:** Would you put arbitrary user text in a metric label?

## Production operations and SRE

### 79. What is an SLI versus an SLO?

An SLI is a defined measurement such as the fraction of eligible acceptance requests meeting the contract. An SLO is the desired target over a window. Example99.95% availability is a design target here, not a production measurement.

**Follow-up:** Define eligibility and exclusions before calculating the percentage.

### 80. What is an error budget?

It is the permitted amount of bad service under an SLO, measured using the same denominator/window. It informs change and reliability decisions rather than excusing unknown incidents. Request-based and time-based budgets can tell different stories and must not be mixed casually.

**Follow-up:** For30days at99.95%, what is the time-based budget, and why may request-based impact differ?

### 81. Why p95/p99 instead of only average latency?

Averages hide slow tail requests that may correspond to retries, lock waits or specific dependencies. Percentiles describe a distribution for a defined operation/window, and histogram resolution affects estimates. Measure acceptance separately from authorization and do not average precomputed percentiles across instances.

**Follow-up:** Can p95 improve while the worst1% gets much worse?

### 82. What is saturation?

It is resource demand approaching or exceeding capacity, such as a full connection pool, worker queue or disk. Latency often rises before total failure. Adding replicas without increasing a constrained database can increase contention rather than restore throughput.

**Follow-up:** Which signal distinguishes CPU saturation from lock contention?

### 83. What should operational logs contain?

Safe resource IDs, correlation IDs, stage/status, duration and failure classification are useful. Customer names, account details, credentials, full provider bodies and raw policy queries are not required for normal troubleshooting. Durable business audit is a separate record with its own permissions/retention.

**Follow-up:** Why is dumping an entire request body an unsafe debugging shortcut?

### 84. How do you investigate a slow authorization?

Correlate the request with network timings/retries, database lock/pool waits and provider health. Check whether submission and other endpoints remain healthy. Preserve the stable transaction reference and look up ambiguous downstream outcomes instead of generating fresh instructions.

**Follow-up:** Why does provider /health200 not prove the authorization endpoint meets its SLO?

### 85. How do metrics differ from traces?

Metrics aggregate rates/distributions; logs record events; traces connect spans across a request path. Correlation IDs provide useful linkage but are not a full distributed tracing deployment. This project should only claim the instrumentation actually configured.

**Follow-up:** How would you add trace context across Kafka and HTTP without exposing customer data?

### 86. What makes a useful incident root cause?

It explains the mechanism and contributing conditions, backed by evidence. Restarting a process is mitigation, not a root cause. The write-up should connect symptom, detection, investigation, mitigation validation and permanent change with owners and dates.

**Follow-up:** How would you distinguish correlation from a proven causal failure?

### 87. What does readiness differ from liveness?

Liveness asks whether the process should keep running; readiness asks whether it can serve its current contract. Restarting a healthy process because a shared database is down can worsen an incident. The health contract must name which dependencies gate readiness and how event backlog affects service promises.

**Follow-up:** Should a Kafka outage make a transaction acceptance API unready when outbox buffering works?

### 88. How would you monitor reconciliation operations?

Track mismatches by controlled classification, open work-item counts, unresolved age and run completion/failure. Totals must retain currency, and variance alone can hide offsetting errors. Avoid transaction IDs as metric labels; use drill-down records for individual evidence.

**Follow-up:** Could a drop in mismatch count mean the reconciliation job stopped running?

## Testing and verification

### 89. What does a unit test prove?

It proves an isolated rule or computation for selected inputs, such as a transition edge or reconciliation classification. It cannot prove real transaction isolation, migrations or network timeouts. Prefer tests of observable invariants over assertions that simply mirror every implementation line.

**Follow-up:** Which financial property would you test independently of the framework?

### 90. What does an API integration test add?

It exercises routing, validation, auth/error shape and service/database behavior together. It can reveal alias, dependency-wiring or commit failures that pure tests miss. A test client still differs from a real deployed HTTP server, so the demo script adds network-level evidence.

**Follow-up:** What does an in-process client not prove about container routing?

### 91. Why test PostgreSQL races explicitly?

A sequential replay test cannot exercise two transactions that both miss the initial lookup and race to claim a key. Coordinate threads/processes and assert one accepted row, one claim and no duplicate journal/outbox effects. Use the actual database engine whose transaction semantics you claim.

**Follow-up:** Why is a random sleep a weaker race test than a barrier or controlled interleaving?

### 92. How do you test ledger balance?

Test valid postings, reject invalid amounts/accounts/currency and assert each persisted journal exposes one equal debit/credit pair. Test rollback after an injected later failure. A structural paired-row design should also have direct database-constraint tests so application bypass cannot create an unbalanced row.

**Follow-up:** How would a future multi-leg journal change your invariant tests?

### 93. Which reconciliation cases matter?

Exact match, amount/currency/status differences, missing internal/external, duplicates, late arrivals, multiple simultaneous anomalies and signed refund totals. Test input-order independence and immutable prior runs. Zero aggregate variance must not suppress record-level exceptions.

**Follow-up:** Construct two mismatches whose total variance is zero.

### 94. How do you test network retry behavior?

Control response sequences and injected time/sleep so tests assert attempt counts, stable headers and delay bounds without becoming slow. Cover400,429,500, malformed success and transport timeout. A real delayed HTTP server verifies that configured timeout behavior reaches the transport.

**Follow-up:** What should happen if malformed JSON arrives with HTTP200?

### 95. How do you test duplicate Kafka effects?

Publish the same event identity twice and assert one consumer receipt/projection effect. A changed body under the same ID must fail safely. Also test database commit before offset commit and out-of-order versions; producer send success alone does not prove consumer correctness.

**Follow-up:** What if the first delivery commits but the process dies before acknowledgement?

### 96. Why include a load script outside ordinary tests?

A local benchmark characterizes throughput, tail latency and errors under controlled concurrency without slowing every build. It creates synthetic unique instructions and reports its workload scope. It is not a production capacity result because hardware, topology, data size and dependency behavior differ.

**Follow-up:** Why can a100-request result say little about steady-state10,000,000-row behavior?

### 97. What should CI actually claim?

Only checks that run successfully: Python/static/API tests, PostgreSQL/Kafka integration, frontend build and Compose validation. Upload reports to diagnose failures. A build-and-test workflow is not deployment, availability proof or regulatory certification.

**Follow-up:** What evidence distinguishes a skipped broker test from a passed broker test?

### 98. How do you report a blocked verification?

State the exact command, environment dependency and observed failure, then separate verified results from unverified claims. Do not relabel unavailable tests as passed or rewrite tests to skip a real defect. Fix independent issues while preserving an honest limitation record.

**Follow-up:** If Compose config passes but containers cannot start, what has and has not been proven?

## Security, privacy and audit

### 99. What is authentication versus authorization?

Authentication establishes caller identity; authorization decides which operation/resource that identity may access. HTTP Basic plus reader/operator roles demonstrates a local boundary. Production also needs TLS, centralized identity, object/tenant checks, lifecycle management and audit review.

**Follow-up:** Why is knowing a transaction UUID not sufficient permission to read it?

### 100. Why is the no-auth mode restricted?

It lowers local setup friction for synthetic data but must not become an internet-facing default. The project requires explicit demo settings and loopback operation. The operations console and API should use the same authorization contract rather than assuming UI-hidden buttons are secure.

**Follow-up:** Can a reader call the API directly even if a button is disabled?

### 101. Where should secrets live?

Environment/configured secret stores supply credentials; ignored local .env is only a demo convenience. Generated local passwords are never printed or committed. Production needs rotation, least-privilege identities and retrieval/access audit rather than long-lived shared credentials in source.

**Follow-up:** Why is deleting a committed key from the latest commit not enough?

### 102. What is least privilege for MCP?

Tools receive only the read evidence needed for investigation and omit customer/account/free-text content. There are no financial mutation tools to invoke. Read-only annotations are hints; the implemented tool set and server authentication/authorization enforce the actual boundary.

**Follow-up:** Why would a readOnlyHint annotation not make an unsafe function safe?

### 103. What should an audit record contain?

It identifies the resource, action, actor, timestamp, predecessor/result and correlation ID with necessary bounded reason/notes. Audit persistence shares the business transaction so committed money changes have evidence. Operational logs have a different retention/use case and are not the sole financial audit.

**Follow-up:** How would you protect audit records from the same database user that writes business data?

### 104. Why sanitize provider errors?

Provider bodies can contain secrets, sensitive customer fields or internal stack traces. The adapter translates them to safe error classes while retaining bounded metadata such as status/attempt classification. Returning raw bodies turns a dependency defect into a data exposure.

**Follow-up:** What could a harmless-looking exception string reveal about SQL or credentials?

### 105. What is a metric cardinality risk?

Every unique label combination creates a time series. Transaction/customer IDs or raw error messages can exhaust metrics storage and expose sensitive data. Use bounded labels such as stage/status/currency and retain per-record drill-down in controlled APIs/logs.

**Follow-up:** Why should requestId be in logs rather than a Prometheus label?

### 106. What does synthetic data mean here?

References, names, amounts and policies are invented for the demo, not anonymized exports of real customer systems. DEMO-prefixed accounts avoid realistic full account numbers. The disclaimer also prevents misleading claims of employer affiliation or professional deployment.

**Follow-up:** Why can a supposedly anonymized production dataset still create privacy risk?

### 107. How would you add object-level authorization?

Associate resources with an authorized organization/tenant and constrain every lookup/mutation by that scope, including MCP and batch paths. UUID randomness is not a permission control. Test cross-tenant access and avoid leaking existence through inconsistent errors.

**Follow-up:** Which service methods would need an explicit security context?

### 108. Why separate correction authority from explanation?

An assistant can summarize evidence incorrectly or follow injected content. Granting it financial mutation authority turns an answer failure into money movement. Keep approval/execution in authenticated human-controlled workflows with independent policy checks and audit.

**Follow-up:** What additional controls would a future proposed-action tool need before execution?

## MCP, RAG and safe AI operations

### 109. What is MCP doing in this project?

It is a model-facing protocol exposing named, typed read-only tools through the official SDK. The tools delegate to existing services and return sanitized bounded evidence. MCP is an adapter, not the transaction engine or a permission system by itself.

**Follow-up:** Why not duplicate reconciliation logic inside the tool handler?

### 110. What is the RAG pipeline?

Bundled synthetic runbooks are chunked, converted to vectors, ranked for a query and bounded before answer generation. The response includes source citations. Retrieval can miss evidence, and generation can still be wrong; the pipeline narrows context rather than proving truth.

**Follow-up:** What should happen when no passage is relevant?

### 111. What do feature-hash embeddings capture?

They encode lexical token overlap into fixed-dimensional signed vectors. They are deterministic and useful for an inspectable baseline, but collisions and vocabulary mismatch limit semantic retrieval. They are not comparable to a modern pretrained embedding model merely because both produce vectors.

**Follow-up:** Why might 'funds not aligned' fail to retrieve a 'settlement variance' passage?

### 112. Why bound retrieval context?

It controls response size, model cost and exposure of irrelevant information. TopK and character limits are enforced before any optional model call. More context can add contradictory or injected instructions rather than improve an answer.

**Follow-up:** How do you preserve source identity when truncating evidence?

### 113. What is a hallucination here?

It is an unsupported claim, such as inventing a provider outage or asserting a mismatch was corrected without evidence. The deterministic incident assistant distinguishes observed records from possible causes and proposed checks. An external model's fluent wording does not increase its authority.

**Follow-up:** Could a correct citation still accompany an unsupported conclusion?

### 114. What is prompt injection?

Untrusted documents or user content can contain instructions aimed at overriding the assistant's task or permissions. Treat retrieved text as evidence, never as authorization to execute tools or change money. The tool surface remains read-only even if text asks for a reversal.

**Follow-up:** Which test proves the server has no mutation tool even under an adversarial question?

### 115. Why keep the incident assistant deterministic?

It can assemble real mismatch/run/transaction evidence and static investigation steps without external model latency or privacy exposure. The output labels hypotheses and cites relevant runbooks. Optional knowledge generation is separate; the incident endpoint does not silently invoke a provider.

**Follow-up:** What useful investigation task can it complete without claiming root-cause certainty?

### 116. What is retrieval failure versus generation failure?

Retrieval failure selects missing/irrelevant evidence; generation failure misuses or invents conclusions from the supplied evidence. Evaluate them separately with known queries, passage relevance and answer support. Swapping the model does not fix a broken matching corpus.

**Follow-up:** How would you build an evaluation set from the synthetic runbooks?

### 117. Why are tool output fields restricted?

A model does not need customer display names, account references, network references or free-text resolution notes to inspect status and mismatch amounts. Limiting the schema reduces accidental exposure and injected content. REST operator access can serve a different permission purpose than model context.

**Follow-up:** How would you test privacy by searching serialized tool output?

### 118. What would production AI evaluation add?

A reviewed corpus, access-controlled retrieval, adversarial tests, groundedness/citation scoring, provider/privacy review, versioned prompts and measured usefulness. Human feedback should distinguish correct uncertainty from confident invention. No evaluation metric grants financial write authority automatically.

**Follow-up:** How would you detect an assistant that always cites sources but never answers the actual question?

## JavaScript operations console

### 119. Why keep financial rules out of React?

The UI can guide users but every command must be validated by the backend under current database state. Hidden buttons and client checks are usability features, not authorization. The same rule must hold for curl, scripts, MCP reads and future adapters.

**Follow-up:** What if a user manually sends a forbidden transition from browser devtools?

### 120. How should the console represent stale data?

It should distinguish loading, error, empty and successfully fetched states and expose source/refresh context where reporting is eventual. A failed refresh must not look like zero exceptions. Command responses should update current version/state before the next operation.

**Follow-up:** How could an empty table conceal an authorization failure?

### 121. Why use stable keys in React lists?

Stable resource UUIDs preserve component identity across updates. Array indexes can associate UI state with the wrong row after sorting/insertion, which is risky in an operations queue. Displayed identity and command target must remain aligned.

**Follow-up:** What bug can occur if a selected exception row moves after refresh?

### 122. How do you display minor units safely?

The backend remains the authority for integer money and supported currency scale. The UI formats cents for human readability without using floating arithmetic to create new financial instructions. JavaScript's safe-integer range and the application's bounded amounts must be considered for totals.

**Follow-up:** Why must parsing a formatted dollar string never silently round a submission?

### 123. Where should browser credentials live?

The local console should avoid embedding credentials in source or persisting them unnecessarily. The server validates Basic credentials on each protected request. Production should replace this demo mechanism with a reviewed identity flow and secure transport/session policy.

**Follow-up:** Why is a frontend .env variable not secret once bundled?

### 124. What is a meaningful browser test?

It starts the real UI/API, signs in using synthetic credentials, loads operational data and exercises a supported workflow or error state. A successful JavaScript build only proves bundling/type syntax constraints, not functional routing or API integration. Check accessibility and narrow-screen behavior as well.

**Follow-up:** What evidence would prove the UI did not merely render hardcoded sample totals?

### 125. How should a409 command conflict appear?

Explain that the resource changed or the action is no longer valid, refresh its current state/version and let the operator reconsider. Automatically repeating a financial command with a new key is unsafe. Preserve requestId for diagnosis without exposing internal stack details.

**Follow-up:** Why should a stale exception-resolution form not silently overwrite newer notes?

### 126. What is CORS and what does it not do?

CORS controls which browser origins may read cross-origin responses under browser enforcement. It is not authentication and does not stop curl or server-to-server requests. Limit development origins deliberately and keep actual authorization on every protected API route.

**Follow-up:** Could permissive CORS expose a Basic-authenticated API to an untrusted website?

### 127. Why separate request state from domain state?

Loading/error flags describe the UI request; statuses such as CLEARED or RESOLVED describe persisted business state. Mixing them can mislabel a failed request as a declined payment. Keep action progress and authoritative response data distinct.

**Follow-up:** Does an HTTP timeout mean the payment's business status is FAILED?

### 128. How would you improve the console for production operations?

Add accessible confirmations for material commands, clear evidence links, refresh/source age, object-level permissions and reviewed dual approval where required. Avoid hiding engineering implementation details in ordinary business flow unless needed for an operator decision. Measure usability with realistic investigation tasks.

**Follow-up:** What information would an analyst need before resolving an amount mismatch?

## Live exercises

1. Add a new supported transaction query filter without weakening bounded pagination.
2. Add a reconciliation case with offsetting mismatches and assert zero variance still produces work items.
3. Inject failure after capture journal insertion and prove the whole command rolls back.
4. Race two full-refund requests with different keys on PostgreSQL and prove one child exists.
5. Add a UI stale-version conflict state and exercise it in a real browser.
6. Add a runbook query that produces no relevant evidence and verify generation is not invoked.

Question count: **128**. Each question includes an answer and a follow-up.
