# Review summary

This report describes the new Python/JavaScript project under `banking-platform/`. It is independent educational work using synthetic data and public banking concepts, with no employer affiliation or production-deployment claim. The original Java project is a separate, unchanged application. The review branch is `feat/python-js-banking-platform`; publishing or pushing requires the user's permission.

## 1. What changed

A new FastAPI backend, React operations console, relational schema, event worker, fictional network service, tests, demonstrations and study documentation were added. The new GitHub Actions workflow targets this project; it does not replace the original workflow. Existing Java source, root README, Maven configuration and root Compose files were preserved.

## 2. Architecture

The application is a modular monolith. REST and read-only MCP adapters use the same banking services. PostgreSQL holds transactional state, history, paired journals, imports, reconciliation snapshots, operational exceptions, outbox records and reporting projections. Kafka and the worker supply asynchronous delivery and read-model updates. The mock network represents a separate external dependency. SQLite is a disposable local learning option, not the evidence for PostgreSQL concurrency.

## 3. Banking capabilities

Synthetic customers/accounts support card purchases, outbound account-transfer instructions and single full refunds. Instructions pass through validation, authorization, capture, clearing and settlement. The project also demonstrates declines, captured reversals, duplicate protection, clearing imports, mismatches, exception investigation and read-only operational assistance. There are no real funding checks, bank rails or customer balances.

## 4. Important domain entities

`Customer`, `BankAccount`, `FinancialTransaction`, `IdempotencyClaim` and `TransactionHistory` describe accepted instructions. `LedgerAccount` and `JournalEntry` describe financial history; `ledger_posting` is a two-sided database view. `ClearingRecord`, `ClearingImport`, `SettlementBatch`, `SettlementItem` and their audit records cover processing. `ExternalImport`, `ExternalReconciliationRecord`, `ReconciliationRun`, `ReconciliationResult`, `OperationalException` and exception history retain independent evidence and investigation. Outbox, consumed-event and projection tables support asynchronous processing.

## 5. REST endpoints

The principal route families are `/api/customers`, `/api/accounts`, `/api/transactions`, `/api/clearing`, `/api/settlements`, `/api/reconciliation`, `/api/exceptions` and `/api/analytics`. Explicit transaction commands are `authorize`, `capture`, `reverse` and `refund`; batch commands are `ready`, `submit` and `confirm`. Read-only investigation uses `/api/assistant/exceptions/{id}`, `/api/knowledge/search` and `/mcp/`. Health and metrics use `/health` and `/metrics`. See [API_GUIDE](API_GUIDE.md) and the running application's authenticated OpenAPI `/docs` for complete contracts.

## 6. Kafka and event architecture

Version-one envelopes contain an event UUID, type, aggregate UUID, occurrence time, correlation ID and bounded metadata payload. `banking.events.v1` uses aggregate keys and three partitions. The outbox commits with business state; publication is at least once because a crash can occur after broker acknowledgement but before the delivered marker. Consumers deduplicate event IDs/fingerprints and reject older aggregate versions. Bounded retries and a `.DLT` retain processing failures for investigation. Kafka offsets alone cannot protect an external database effect.

## 7. Ledger

Money is integer minor units, limited to USD/EUR/GBP with two decimal places. Each stored journal represents one equal debit and credit, making imbalance structurally unrepresentable. The helper validates known distinct accounts and full transaction amount/currency; a database composite foreign key reinforces the full-value rule. Unique transaction/event identity prevents repeated capture/settlement journals. Update/delete triggers preserve committed journals. Corrections append compensating history. This simplified two-leg ledger does not calculate spendable balances or implement a complete general ledger.

## 8. Settlement workflow

Cleared transactions of one business date/currency enter bounded batches. PostgreSQL locks eligible rows, while unique transaction membership is the final duplicate-settlement guard. Commands require the current version and legal predecessor. Confirmation changes all member states, journals, histories and outbox records atomically. Gross debit, gross credit and signed net totals separate payments from refunds. Confirmation is an educational operator assertion, not actual external money movement.

## 9. Reconciliation workflow

Independent external records preserve duplicates and import identity. A run compares one date/currency under a consistent PostgreSQL snapshot and stores immutable evidence. It starts with settlement-eligible instructions and also loads known transaction references present in external evidence, retaining their actual state for status-mismatch diagnosis. Classifications include amount, currency, status, duplicate external, missing internal/external and late-arrival anomalies; several can apply to a reference. Signed refunds avoid inflating outbound totals. Internal 50000 versus external 45000 produces a 5000-minor-unit variance. Reruns create new snapshots. A batch becomes reconciled only when every member matches.

## 10. Exception workflow

Material mismatch evidence creates a deduplicated work item. Operators move `OPEN → INVESTIGATING → RESOLVED` with assignment, notes and a version check. Compare-and-set prevents one analyst overwriting another; history retains identity/time/correlation. Resolving an exception never changes a transaction, journal or original reconciliation result. Financial correction is a separate explicit process.

## 11. Data pipeline

Kafka consumption builds transaction, settlement, exception and reconciliation projections in PostgreSQL. Reporting is eventually consistent with the write model. Analytics identify `KAFKA_PROJECTION` versus the explicit broker-disabled `DEMO_WRITE_MODEL` source and expose outbox backlog. Currency-separated totals stay exact integers; decimal half-even rounding is explicit for average minor units. Authorization/decline rates use completed decisions only and return null when there are no decisions. The console preserves large JSON integers and uses `BigInt` for monetary display.

## 12. Testing strategy

pytest covers policies, monetary validation, ledger balancing, API contracts, security, HTTP status/timeout/retry behavior, rich reconciliation cases, replay and rollback. Alembic creates test schemas. Real PostgreSQL tests prove unique-claim races, locking, concurrent capture/settlement, exception versions and consumer/projection races. Real Kafka tests exercise transport, duplicates and dead letters. Frontend tests check precise formatting; browser checks cover visible behavior and API integration. Build, Compose validation and real service startup are recorded separately.

## 13. MCP and RAG

Eleven MCP tools retrieve sanitized facts or runbooks; none can move money, settle a batch, reverse/refund a payment, change a balance or resolve an exception. Runbooks are packaged under `backend/app/runbooks/`. Chunking, 512-dimensional feature hashes, lexical overlap, ranking and bounded context provide an educational retrieval baseline. Default answers and incident explanations are deterministic and cited. Optional HTTP model generation is disabled by default. Retrieved instructions remain untrusted, and citations do not establish truth or authorization.

## 14. Observability

The API exposes liveness, database readiness and Prometheus metrics. Safe JSON logs carry request IDs and route/status/timing metadata. Network latency/failures/retries, outbox pending/oldest age, delivery latency, duplicate events and worker consumer lag connect technical symptoms with business impact. Metrics in separate processes must be scraped separately. Example SLOs are documented design exercises, not measured production guarantees.

## 15. Docker and CI

The independent Compose project contains PostgreSQL, Kafka, mock network, API, worker and console. Generated credentials live only in ignored `.env`; health checks gate startup. Docker builds run the API/mock as unprivileged users. The project-specific workflow runs Python/static tests, PostgreSQL/Kafka integration, frontend build and Compose validation and retains reports. No deployment workflow or production environment is claimed.

## 16. Run locally

From `banking-platform/`:

```sh
python3 scripts/create_env.py
docker compose up --build
python3 scripts/demo_end_to_end.py
python3 scripts/demo_duplicate_transaction.py
```

Open the console at `http://127.0.0.1:5173` and API reference at `http://127.0.0.1:8080/docs`. Use the generated local credentials. For the loopback SQLite alternative and installation commands, see [README](../README.md). Destructive demo resets are explicit: stop services, then use `docker compose down -v` only when intentionally deleting this project's local data.

## 17. What has actually been verified

Final source verification passed **118 Python tests**, with **86% statement coverage**, including real PostgreSQL concurrency, real Kafka duplicate/DLT transport, schema/model alignment, money controls, REST security and MCP protocol tests. No integration tests were skipped in this full run. The separate mock service passed **5 tests**; frontend regression tests passed **4 tests**, and its production build passed.

All six Compose services became healthy. The secured production nginx browser test passed desktop/mobile navigation, memory-only login, payment creation/authorization/capture/clearing, settlement, a $50 mismatch, cited incident evidence, audited exception resolution and knowledge retrieval, with zero JavaScript runtime errors. Live PostgreSQL demos passed full payment/refund processing, eight concurrent submissions producing one creation/seven replays, and a deliberate network timeout returning503 while preserving RECEIVED. The optional100-request acceptance workload had zero errors; this is a local benchmark, not a capacity claim. Worker lag and pending outbox were observed at zero after processing.

Cloud-only CA and storage workarounds were needed for this7.9GB VFS executor. Source Dockerfiles remain standard; PostgreSQL/Kafka images were flattened locally only after exact runtime-config and filesystem equality checks. The final frontend container used the already built nginx runtime plus the exact final locally built static bundle and healthcheck. See [VERIFICATION](VERIFICATION.md) for precise commands and limits. GitHub Actions has not run remotely because nothing has been uploaded or pushed.

## 18. Remaining limitations

- Synthetic authorization and operator-confirmed settlement; no real rails, funds reservation, card-network certification or regulatory controls.
- Full single refunds only; no partial allocation, disputes, FX, fees, interest or account-balance engine.
- Two-leg journals rather than a complete accounting platform; privileged database administrators remain outside application immutability guarantees.
- Synchronous bounded authorization holds a row lock; long-running real rails need durable orchestration and explicit total deadlines.
- Single PostgreSQL/Kafka instances, local plaintext infrastructure, HTTP Basic and simple worker scheduling; production requires identity/TLS, backup/restore, controlled migrations, capacity and outage exercises.
- External evidence is append-only with no replacement/supersession endpoint; corrected duplicate evidence requires a future audited amendment policy.
- Bounded imports/runs and explicit source-cutoff assumptions; larger banking files require staging, retention and resumability design.
- Feature hashing is lexical; optional providers need separate privacy, retrieval and supported-claim evaluation. No autonomous financial remediation exists.
- Local benchmarks describe the local acceptance workload only. AWS and multi-region documents are hypothetical designs.

## 19. Top 15 files to study

Paths are relative to `banking-platform/`.

| File | What to explain |
| --- | --- |
| `backend/app/transactions.py` | Submission identity, rollback recovery, lifecycle, compensation and transaction boundaries |
| `backend/app/models.py` | Core relationships, amounts, versions and financial uniqueness |
| `backend/app/ledger.py` | Balanced two-leg construction and full-value validation |
| `backend/alembic/versions/0001_transactions_ledger.py` | Database constraints, posting view and journal immutability |
| `backend/app/network.py` | Timeout ambiguity, stable reference, bounded retry and response validation |
| `backend/app/clearing.py` | Exact confirmation and audited CSV ingestion |
| `backend/app/settlement.py` | Eligible membership, net totals, versioned commands and atomic confirmation |
| `backend/app/reconciliation.py` | Deterministic matching, snapshots, classifications and variance |
| `backend/app/exceptions.py` | Work-item deduplication, compare-and-set and investigation audit |
| `backend/app/events.py` | Atomic outbox, publish race, consumer deduplication and projection versions |
| `backend/app/worker.py` | Broker transport, offsets, retry/DLT and lag |
| `backend/app/main.py` | Authentication, Problem Details, request correlation, health and metrics |
| `backend/app/mcp_server.py` | Read-only authority, input limits, transport and privacy allowlists |
| `frontend/src/App.jsx` | Operational UI, real API state, human commands and failure presentation |
| `backend/tests/test_transactions_api.py` | Executable money/idempotency/lifecycle/API/concurrency evidence |

Use [CODE_WALKTHROUGH](CODE_WALKTHROUGH.md) for 23 files with purpose, methods, business/technical reasons, failure modes, interview questions and production improvements.

## 20. Top 20 concepts to explain

1. Authorization versus capture, clearing, settlement and reconciliation.
2. Transaction identity versus idempotency key versus downstream reference.
3. Same-key/same-request replay and same-key/different-request conflict.
4. Why database uniqueness defeats races that process locks cannot.
5. PostgreSQL transaction abort, rollback and fresh winner reads.
6. Legal state transitions, version predicates and complete audit history.
7. Debit/credit equality, accounting meaning and why balance alone is insufficient.
8. Integer money, currency separation and exact JavaScript aggregate display.
9. Append-only reversal/refund compensation instead of deleting financial history.
10. `FOR UPDATE`, `SKIP LOCKED`, compare-and-set and their different purposes.
11. Atomic batch confirmation and unique settlement membership.
12. Reconciliation snapshots, multiple anomalies and zero-net offsetting mismatches.
13. Exception resolution versus financial correction.
14. Database/broker dual-write failure and the transactional outbox.
15. At-least-once publication, event-ID deduplication and crash windows.
16. Kafka keys/partitions, consumer groups, offsets, lag, replay and dead letters.
17. Eventual read models and aggregate-version protection against old events.
18. Timeout ambiguity, retry budgets, dependency saturation and incident evidence.
19. Authentication, authorization, privacy, correlation IDs, SLIs and example SLOs.
20. MCP authority boundaries, retrieval failure, prompt injection and cited evidence limits.
