# Translating banking requirements into executable controls

Requirements need acceptance evidence, failure behavior and an operating procedure. The following examples map business language to the actual educational implementation. They are not claims about any employer's internal controls.

## BR1: A duplicate instruction must not create duplicate financial transactions

**Functional requirement:** One accepted submission identity has one original financial result. A different normalized request cannot reuse that identity.

**API requirement:** `POST /api/transactions` requires `Idempotency-Key`; first acceptance returns 201, matching replay 200, conflicting payload 409. External reference is independently unique.

**Database/concurrency design:** Unique `IdempotencyClaim` key, normalized SHA256 fingerprint and original response/transaction identity commit with the transaction/history/outbox. Two callers may both miss a lookup; the unique insert decides the winner. The loser rolls back and reads the winner in a new transaction. No Python process lock is the correctness mechanism.

**Tests:** Sequential replay/conflict, normalized-equivalent request, simultaneous same-key requests on PostgreSQL, different-key same-reference conflict, rollback without orphan transaction/journal/outbox.

**Monitoring/operation:** Watch replay/conflict volume and investigate unusual upstream retries using safe request/transaction IDs. A timeout retry must retain the original key; operators must not invent a fresh business reference simply to bypass 409.

## BR2: Every financial event must remain balanced and auditable

**Functional requirement:** Capture, reversal and settlement preserve equal debits/credits in one currency; corrections retain history.

**API requirement:** Lifecycle commands create journals through the service. No public endpoint updates/deletes arbitrary posting amounts or directly sets a balance.

**Database/design:** `JournalEntry` stores paired distinct ledger accounts, one positive bounded integer amount and currency. Account identifier/currency checks and a composite foreign key to the transaction's identity, amount and currency protect consistency. The `ledger_posting` view presents both sides. Unique transaction/event journal identity prevents duplicate capture/settlement effects, and database triggers reject journal updates/deletes.

**Tests:** Unbalanced posting inputs, zero/negative/noninteger money, different currencies, unknown/equal accounts, database constraint bypass attempts and rollback after a later command failure.

**Monitoring/operation:** Use journal and transaction history for evidence; reconcile independently. A balanced wrong entry remains possible, so never describe balance equality as complete financial correctness. Production needs restricted database roles, period controls, trial-balance reconciliation and approved adjustments.

## BR3: A cleared payment must enter at most one settlement batch

**Functional requirement:** Only eligible cleared transactions of the selected date/currency are included, and totals describe exactly those members.

**API requirement:** Batch creation has bounded `maxItems`; ready/submit/confirm require `expectedVersion` and a reason. The current batch view exposes transaction count, gross debit/credit and signed net.

**Database/concurrency design:** Selection locks eligible records with `SKIP LOCKED` on PostgreSQL; a unique settlement-item transaction ID protects final membership under races. Batch confirmation and member settlement journals/statuses share one database transaction. Versions and predecessor checks reject stale or illegal commands.

**Tests:** Mixed-currency/date selection, refund direction, concurrent batch builders, duplicate confirmation, stale version and injected failure rolling back the whole batch.

**Monitoring/operation:** Track batches by state, pending age and amount/currency; compare independent confirmation evidence. This project's confirmation is a synthetic operator assertion, not a real settlement-network call. Cancellation/reassignment policies require further design.

## BR4: A variance must identify its contributing records

**Functional requirement:** A run stores totals and record-level mismatch evidence, including multiple simultaneous anomalies.

**API requirement:** Start a date/currency run, read its snapshot and paginated mismatches, inspect a result and rerun into a new linked run. Independent external evidence preserves source identity and duplicate rows.

**Database/design:** Immutable `ReconciliationRun`/`ReconciliationResult` retain internal/external values and classifications. PostgreSQL uses a repeatable-read snapshot for a run; bounded whole-transaction retries address conflicts. Run size is capped at 10,000 records; external submission max 1,000 rows.

**Tests:** Exact, amount, currency, status, missing internal/external, duplicate, late arrival, signed refund, input-order independence, zero-net offsetting mismatches and stable prior snapshots.

**Monitoring/operation:** Monitor run success and mismatch population as well as net variance. A zero variance can hide offsetting errors. A failed or absent run must not appear to be a clean match day.

## BR5: Analysts must not silently overwrite each other's findings

**Functional requirement:** Investigation follows an explicit lifecycle with assignment, notes, actor/time and an audit trail. Closing a work item does not alter financial evidence.

**API requirement:** PATCH exception includes current `version`, status, team and required resolution notes. `OPEN → INVESTIGATING → RESOLVED`; stale updates return 409.

**Database/concurrency design:** Compare-and-set update checks the old version atomically and appends history in the same commit. Evidence-based issue identity reuses the same issue for an identical rerun; changed evidence creates a distinct issue.

**Tests:** Concurrent analysts on PostgreSQL, stale version, invalid transitions, missing notes, rerun deduplication and unchanged journals/results after resolution.

**Monitoring/operation:** Track unresolved count/age and assigned workload. On 409 reload evidence and decide again; never auto-overwrite new notes. A production material-exception process may require separate approver and investigator roles.

## BR6: A network outage must not create uncontrolled duplicate decisions

**Functional requirement:** Bound elapsed attempts and retain the same downstream business identity despite ambiguous responses.

**API requirement:** Authorization returns a sanitized 502 for permanent/malformed provider responses or 503 when transient attempts are exhausted. Request ID links the attempt evidence.

**Adapter/design:** Stable transaction UUID as downstream `Idempotency-Key`, connect/read timeouts, bounded exponential retry for transport/429/5xx, bounded `Retry-After`, strict response size/shape and no redirects to arbitrary origins.

**Tests:** Success,400,401/403/404/409,429,500, malformed/oversized response, timeout, stable headers and bounded delay/attempt count.

**Monitoring/operation:** Inspect network failures/retries/latency, look up the provider reference and preserve local state. A timeout does not prove nonprocessing. Production would add a total deadline, measured concurrency/bulkhead policy and durable orchestration for slow rails.

## BR7: An AI assistant may explain evidence but must not move money

**Functional requirement:** Tools return sanitized bounded facts/runbook citations and cannot authorize, settle, reverse or close material exceptions.

**API requirement:** MCP exposes only read operations; assistant exception explanation is GET. Knowledge search is read-only despite POST.

**Design:** Existing services are the only source of banking facts. Tool output allowlists omit names/account/network/free-text fields; official MCP SDK handles transport. Incident answers are deterministic and distinguish observed records from possible causes. Retrieved text is untrusted.

**Tests:** Real MCP initialize/list/call, tool-set mutation exclusion, privacy string checks, bounded paging/query/context and prompt-injection content without financial effect.

**Monitoring/operation:** Keep model-provider mode disabled by default; evaluate evidence relevance and unsupported claims before enabling optional generation. Citations support review but never substitute for human approval or authorization.
