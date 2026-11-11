# Code walkthrough:23 files and boundaries

Paths below are relative to `backend/` unless they begin `../`. Read [TRANSACTION_WALKTHROUGH](TRANSACTION_WALKTHROUGH.md) first, then inspect the failure paths. The original Java project is independent and unchanged.

## 1. `app/main.py`

**Purpose:** Process and HTTP security boundary.

**Important methods/types:** `create_app, request_controls, validate_security, readiness, metrics`.

**Business reason:** An operator command must have identity, a safe failure response and traceable request ID.

**Technical reason:** FastAPI middleware validates Basic roles and request metadata; exception handlers return Problem Details.

**Failure modes:** Misconfigured demo exposure, missing credentials, database outages, accidental high-cardinality metrics.

**Interview questions:** Which routes are public, reader-only and operator-only? Why is readiness different from liveness?

**Potential production improvements:** Replace demo Basic with centralized OIDC/TLS and scoped object authorization; add end-to-end tracing.

## 2. `app/api.py and app/schemas.py`

**Purpose:** REST contracts without business orchestration.

**Important methods/types:** `create_transaction, authorize, capture, refund; TransactionRequest and ActionRequest`.

**Business reason:** Callers need explicit money/reference/date rules and predictable replay status.

**Technical reason:** Pydantic strict integers, camelCase aliases, bounded references and extra-field rejection; controller delegates to TransactionService.

**Failure modes:** Boolean/float money, malformed UUIDs, missing idempotency key, stale or illegal commands.

**Interview questions:** Why does valid JSON still need database/business validation?

**Potential production improvements:** Version APIs deliberately and add contract compatibility tests before introducing additional channels.

## 3. `app/models.py`

**Purpose:** Core persisted identities and accounting constraints.

**Important methods/types:** `Customer, BankAccount, FinancialTransaction, IdempotencyClaim, TransactionHistory, LedgerAccount, JournalEntry`.

**Business reason:** Transactions, originals/refunds and ledger history need durable relationships.

**Technical reason:** SQLAlchemy models mirror Alembic constraints; UUIDs and UTC dates/times stay explicit.

**Failure modes:** Orphan links, duplicate external references, wrong account currency or invalid money.

**Interview questions:** Which invariant survives two API processes racing? Find its database constraint.

**Potential production improvements:** Restrict database roles, add period controls and evaluate partitioning only after measured growth.

## 4. `app/transactions.py`

**Purpose:** Central aggregate and transaction boundaries.

**Important methods/types:** `TransactionService.create/authorize/capture/reverse/refund; transition, get_transaction_locked, ledger_settle`.

**Business reason:** Only legal lifecycle steps create money effects, and repeated instructions must not duplicate them.

**Technical reason:** Unique request claims recover after rollback; row locks plus version predicates coordinate state changes; history/outbox share the commit.

**Failure modes:** Unique races, failed downstream call, duplicate capture/refund, invalid predecessor and local commit after remote success.

**Interview questions:** Draw the timeout and unique-key race paths. Why cannot a database rollback undo HTTP?

**Potential production improvements:** Move long authorization flows to a durable process manager; add explicit total deadlines and real funding policies.

## 5. `app/ledger.py`

**Purpose:** Balanced journal construction.

**Important methods/types:** `Posting, post_journal, paired_post`.

**Business reason:** Every modeled financial event has equal debit and credit in one currency.

**Technical reason:** Two equal validated postings become one paired JournalEntry; the database posting view expands it to two sides.

**Failure modes:** Unbalanced input, noninteger or wrong currency money, equal/unknown accounts, duplicate journal event.

**Interview questions:** What is structurally guaranteed, and what could still be economically wrong?

**Potential production improvements:** Add reviewed multi-leg journals, accounting periods, trial balances and stronger database-role immutability.

## 6. `alembic/versions/0001_transactions_ledger.py`

**Purpose:** Reviewable initial banking schema.

**Important methods/types:** `upgrade and downgrade`.

**Business reason:** Financial safety must not rely only on Python checks.

**Technical reason:** Explicit tables, indexes, checks, foreign keys, seeded synthetic ledger accounts and ledger_posting view.

**Failure modes:** Schema drift, invalid upgrade order, cross-currency link, unsafe destructive rollback.

**Interview questions:** Explain why migration tests on PostgreSQL matter even when SQLite passes.

**Potential production improvements:** Use expand/contract rollouts and production-scale migration rehearsal rather than startup DDL.

## 7. `app/clearing.py`

**Purpose:** Confirmed details and audited file ingestion.

**Important methods/types:** `ClearingService.create/import_csv/get_import/import_rows; _record, _parse_row`.

**Business reason:** A payment must not silently settle with a different amount/currency/date, and bad rows need evidence.

**Technical reason:** Exact UTF-8 CSV schema, bounded file/row counts, SHA256 content identity, savepoint per row and transactional summary.

**Failure modes:** Malformed schema/row, duplicate file/reference, unknown transaction, incorrect network details and ineligible state.

**Interview questions:** Why are independent reconciliation evidence and clearing confirmation separate concepts?

**Potential production improvements:** Add source authentication, signed files, resumable staged imports and a defined duplicate retention policy.

## 8. `app/settlement.py`

**Purpose:** Batch membership and controlled confirmation.

**Important methods/types:** `SettlementService.create/ready/submit/confirm/items/history; reconcile_in_session`.

**Business reason:** One transaction belongs to one batch, and confirmation must not partially settle its members.

**Technical reason:** Date/currency selection with row locking, unique membership, gross debit/credit/net totals, expectedVersion CAS and shared financial commit.

**Failure modes:** Overlapping builders, stale commands, empty batch, member changed before confirmation and whole-command failure.

**Interview questions:** Why does SKIP LOCKED help throughput but not replace uniqueness?

**Potential production improvements:** Add cancellation/reassignment policy, real confirmation adapter and controlled resubmission/lookup semantics.

## 9. `alembic/versions/0002_clearing_settlement.py`

**Purpose:** Clearing and batch relational controls.

**Important methods/types:** `upgrade and downgrade`.

**Business reason:** Imports and batch history need reproducible links and queryable operational queues.

**Technical reason:** Unique clearing references/file hashes/transaction membership, row status checks and lookup indexes.

**Failure modes:** Direct SQL creating duplicate settlement membership or invalid import totals.

**Interview questions:** Which index supports import outcome retrieval? What write cost does it add?

**Potential production improvements:** Plan retention, partitioned large-file staging and incremental validation under real volume.

## 10. `app/reconciliation.py`

**Purpose:** Independent evidence comparison and immutable run snapshots.

**Important methods/types:** `compare_records; ReconciliationService.import_records/create_run/get_run/mismatches/rerun`.

**Business reason:** Operators need record-level causes behind a settlement variance.

**Technical reason:** Pure comparison groups candidates by reference; signed currency-scoped totals and multiple classifications persist under a PostgreSQL repeatable-read run.

**Failure modes:** Duplicates, missing evidence, wrong currency/status, late arrival, run-size cap and serialization conflicts.

**Interview questions:** Can zero variance coexist with mismatches? Why is a rerun a new identity?

**Potential production improvements:** Define externally stable source cutoffs, larger staged streaming populations and approved tolerance/write-off policies.

## 11. `app/exceptions.py`

**Purpose:** Human investigation lifecycle.

**Important methods/types:** `create_exception_in_session; OperationalExceptionService.get/list/update/history`.

**Business reason:** Evidence should become assigned work without silently changing financial records.

**Technical reason:** Evidence-based issue fingerprint, allowed OPEN/INVESTIGATING/RESOLVED transitions, required notes, atomic version predicate and history.

**Failure modes:** Concurrent analyst updates, stale form, invalid transition, repeated identical mismatch and notes missing at resolution.

**Interview questions:** Why does resolving a work item not make the run matched?

**Potential production improvements:** Add separate investigator/approver roles, escalation/aging policy and immutable external audit storage.

## 12. `alembic/versions/0003_reconciliation_exceptions.py`

**Purpose:** Persisted evidence and work-item constraints.

**Important methods/types:** `upgrade and downgrade`.

**Business reason:** Historical mismatches and operator actions must remain inspectable.

**Technical reason:** Run/result links, issue identity uniqueness, status/version/count checks and date/reference/status indexes.

**Failure modes:** Conflicting reruns, orphan results or SQL updates violating count/variance relationships.

**Interview questions:** Where is variance=internal-external enforced? What cannot a row check prove?

**Potential production improvements:** Use restricted DB roles and archival/retention design with reproducible source provenance.

## 13. `app/events.py`

**Purpose:** Atomic event recording and idempotent projections.

**Important methods/types:** `record_event, validate_event, OutboxDispatcher.deliver_next, ProjectionConsumer.accept, refresh_metrics`.

**Business reason:** A committed financial change must retain an event even when Kafka is unavailable.

**Technical reason:** Same-session outbox write; acknowledged publication before delivered marker; event ID/hash dedup and atomic aggregate-version guard.

**Failure modes:** Crash after send, duplicate ID with changed body, out-of-order state, DB race and invalid envelope.

**Interview questions:** Which crash creates a duplicate, and which database invariant absorbs it?

**Potential production improvements:** Add schema-registry compatibility, bounded retention/archival and operational replay tooling.

## 14. `app/worker.py`

**Purpose:** Kafka transport lifecycle and retry/DLT policy.

**Important methods/types:** `run, process_record, _topics`.

**Business reason:** Reporting needs actual broker transport and explicit failure recovery.

**Technical reason:** Creates versioned topics, keyed producer/consumer group, bounded processing attempts, DLT acknowledgement before offset commit and worker metrics.

**Failure modes:** Broker outage, poison event, DLT failure, consumer rebalance and offset replay.

**Interview questions:** Why is committing the offset not the same as committing a business effect?

**Potential production improvements:** Add graceful rebalance/drain exercises, managed broker security and stronger lag/age alerting.

## 15. `app/analytics.py`

**Purpose:** Operational reporting read interface.

**Important methods/types:** `AnalyticsService.daily/transactions/settlements/exceptions`.

**Business reason:** Analysts need currency-scoped volume, authorization and operational summaries without changing the write workflow.

**Technical reason:** Kafka projection tables when enabled; explicit DEMO_WRITE_MODEL fallback, integer/HALF_EVEN average and decimal percentage strings.

**Failure modes:** Stale projection, missing consumer, mixed currency totals, unbounded page or misleading source.

**Interview questions:** Why should a dashboard expose data source/backlog rather than imply immediate consistency?

**Potential production improvements:** Use query-plan/load evidence before denormalizing further; add snapshot age and workload-specific retention.

## 16. `alembic/versions/0004_banking_events_analytics.py`

**Purpose:** Outbox, consumer receipts and read-model schema.

**Important methods/types:** `upgrade and downgrade`.

**Business reason:** Reliable asynchronous effects require durable receipts and projection identity.

**Technical reason:** Outbox sequence/availability indexes, unique event IDs and aggregate projection keys.

**Failure modes:** Receipt without effect if commits are separated; deleting a projection while retaining dedup receipts.

**Interview questions:** How would you rebuild the projection without touching financial source records?

**Potential production improvements:** Use explicit replay/backfill administration with access controls and retained source snapshots.

## 17. `app/network.py`

**Purpose:** Fictional payment-network client.

**Important methods/types:** `NetworkSettings.from_env; PaymentNetworkClient.authorize/_authorize/_retry_delay`.

**Business reason:** An ambiguous timeout must retain one downstream business identity.

**Technical reason:** HTTPX bounded timeouts/attempts, stable UUID key, safe correlation header, strict 4 KiB response schema, transient-only retry and bounded Retry-After.

**Failure modes:** 429/5xx/transport timeout, permanent 4xx, malformed/oversized body and provider already acted.

**Interview questions:** Which failures are retryable and why? Does a read timeout bound the whole request?

**Potential production improvements:** Add a measured total deadline, jitter/concurrency policy, provider lookup and durable orchestration.

## 18. `../demo/network-service/server.py`

**Purpose:** Safe synthetic external dependency.

**Important methods/types:** `HTTP handler and authorization cache`.

**Business reason:** Interviews need a repeatable partial-failure story without real bank integration.

**Technical reason:** Stable-reference cached decision, amount 13 decline and environment-selected timeout/429/500/malformed scenarios.

**Failure modes:** Timeout after decision, duplicate reference conflict and mock restart losing cache.

**Interview questions:** Why does caching the decision before delaying the response teach timeout ambiguity?

**Potential production improvements:** Use a durable mock cache only if cross-restart scenario testing requires it; never treat this mock as real provider semantics.

## 19. `app/knowledge.py`

**Purpose:** Bounded lexical evidence retrieval.

**Important methods/types:** `KnowledgeService.retrieve/search/_model_answer`.

**Business reason:** An assistant should cite relevant synthetic runbooks and acknowledge missing evidence.

**Technical reason:** 80-word chunks with 15-word overlap, 512 signed feature hashes, lexical overlap filter/cosine ranking, top 5/6000-character bounds.

**Failure modes:** Vocabulary mismatch, hash collisions, irrelevant evidence, provider failure and injected source text.

**Interview questions:** Why is this not a production semantic embedding model?

**Potential production improvements:** Evaluate a reviewed corpus and modern embeddings while preserving access control, citations and retrieval-failure behavior.

## 20. `app/assistant.py and app/mcp_server.py`

**Purpose:** Read-only model-facing operations evidence.

**Important methods/types:** `IncidentAssistantService.explain; create_mcp_server and 11 named tools`.

**Business reason:** AI may explain discrepancies but must not authorize, settle, reverse or resolve them.

**Technical reason:** Official MCP SDK transport, bounded inputs, allowlisted sanitized fields, deterministic observed-condition/hypothesis output and citations.

**Failure modes:** Hallucinated causes, prompt injection, unbounded paging and leakage through free text.

**Interview questions:** Which permission is enforced by code rather than readOnlyHint?

**Potential production improvements:** Add evaluated prompts/model providers only where useful; keep execution authority in separate reviewed human workflows.

## 21. `app/common.py and app/errors.py`

**Purpose:** Shared safe representation and request context.

**Important methods/types:** `now, actor, correlation_id, as_dict, validate_page, page_result; DomainError`.

**Business reason:** Every workflow should use consistent time, audit identity and bounded page semantics.

**Technical reason:** Context variables isolate request metadata; explicit serialization avoids ORM leakage and normalizes UTC.

**Failure modes:** Naive timestamps, context leaking across requests, invalid page bounds and raw exception exposure.

**Interview questions:** Why is requestId not the same as a transaction or event ID?

**Potential production improvements:** Keep shared helpers small; add tenant/security context when object-level authorization is designed.

## 22. `../frontend/src/App.jsx`

**Purpose:** JavaScript operations console.

**Important methods/types:** `React component tree, API request helper and operator forms`.

**Business reason:** An analyst needs visible transactions, settlement/reconciliation evidence and safe command feedback.

**Technical reason:** REST-backed views share backend rules; integer money display and current resource versions preserve meaning.

**Failure modes:** Stale selected row, hidden errors shown as zero, stale409, credentials persistence and unsafe monetary parsing.

**Interview questions:** What browser test proves the displayed data came from the real API?

**Potential production improvements:** Add reviewed approval UX, accessibility testing, source-age cues and object-scoped identity.

## 23. `../scripts/demo_end_to_end.py`

**Purpose:** Executable business narrative.

**Important methods/types:** `main and shared demo_http.Api`.

**Business reason:** A reviewer should reproduce the complete flow without manually copying dozens of UUIDs.

**Technical reason:** Loopback-only credential handling, deterministic synthetic amounts, replay/conflict assertions and real HTTP commands.

**Failure modes:** Reused dataset ID, wrong credentials, startup not ready, stale schema or an unexpected response contract.

**Interview questions:** Which checks prove financial progression versus merely HTTP200?

**Potential production improvements:** Extend scenarios with explicit source correction/rerun and controlled restart/recovery evidence.

## Verification reading order

Read the pure comparison/ledger/transition tests, API/security tests, PostgreSQL race tests, then real Kafka/HTTP failure tests. Use [TESTING](TESTING.md) to separate what each proves. Check actual reports in [VERIFICATION](VERIFICATION.md); a test instruction is not evidence that it ran.
