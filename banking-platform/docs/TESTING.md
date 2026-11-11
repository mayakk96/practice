# Testing strategy and verification scope

Run tests from `banking-platform/backend` after installing `.[test]`. Alembic creates each test schema; tests do not use `Base.metadata.create_all` as a substitute for migrations. Unit/API fixtures use a disposable SQLite file. PostgreSQL tests create an isolated temporary schema under `TEST_DATABASE_URL` and remove only that schema afterward. Never point the test credentials at a real financial database.

## Fast local checks

```sh
pytest -m 'not postgres and not kafka'
ruff check app tests
python -m compileall -q app
cd ../frontend
npm ci
npm test
npm run build
```

Pure ledger/transition/reconciliation/retry tests check invariants and classifications. FastAPI integration tests exercise actual routes, Pydantic validation, Problem Details, database rollback and security. HTTPX mocks control status sequences and injected sleep; delayed local HTTP tests verify transport timeouts. MCP tests exercise the official SDK initialize/list/call path as well as privacy/prompt-injection boundaries.

## PostgreSQL integration and concurrency

Start `docker compose up -d postgres` from the project directory. Supply the generated local database password through your shell/environment without committing it:

```sh
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5433/banking pytest -m postgres
```

Tests cover real migrations/constraints, simultaneous idempotency claims, financial command races, settlement assignment/confirmation, consumer receipt/projection version races and exception version conflicts. Barriers or controlled interleavings are more meaningful than hoping two fast requests overlap. A green SQLite test does not prove `FOR UPDATE`, `SKIP LOCKED`, PostgreSQL aborted-transaction recovery or repeatable-read semantics.

The account/transaction/journal schema uses foreign keys and checks in addition to service validation. Direct SQL constraint tests verify that bypassing Python does not permit negative money, missing relationships, duplicate membership or mismatched journal currency/amount.

## Real Kafka transport

Start the project Kafka broker and run:

```sh
KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9095 pytest -m kafka
```

Broker tests publish actual records, consume/replay them and check duplicate effects and dead-letter recovery. Unit worker tests separately inject transient processing failures and verify offset/DLT acknowledgement decisions. The idempotent database consumer tests alone do not prove broker connectivity; producer-send tests alone do not prove read-model correctness.

When no broker/database variables are provided, marked tests can skip. **A skipped test is not a passed integration test.** Check the summary and [verification record](VERIFICATION.md).

## Reconciliation cases

`test_reconciliation.py` covers exact match, missing internal/external, amount, currency, status, duplicate external, late arrival, multiple simultaneous classifications, signed refund totals, unchanged previous snapshots and work-item deduplication. Input-order independence matters because database row ordering must not change the result. Offseting mismatches can sum to zero while remaining operational problems.

A run uses a bounded 10,000-record educational population. PostgreSQL repeatable-read snapshots and bounded whole-run retries make comparisons consistent for that source snapshot, while production still needs explicit external file/source cutoff and larger staging/replay policies.

## Real HTTP demonstration

```sh
python3 scripts/demo_end_to_end.py
python3 scripts/demo_duplicate_transaction.py
python3 scripts/demo_reconciliation_mismatch.py --run-id second-synthetic-demo
```

Append `--no-auth` only against the explicit loopback demo. The end-to-end script checks initial creation, matching replay, conflicting replay, authorization, capture, exact clearing, batch lifecycle, deliberate 50000/45000 mismatch, exception, read-only explanation, decline, reversal, full refund settlement and analytics source. It uses a fixed business date and dataset shape; a fresh `--run-id` permits a new set of identities. A fresh database is required for isolated exact daily totals.

The duplicate demo races eight identical instructions and requires exactly one 201 and seven replays with one transaction UUID. This is useful live evidence, while the PostgreSQL suite proves the database-specific concurrency design.

## Failure exercises

The timeout script expects a fault-configured mock and a 503; it fails if the network unexpectedly succeeds. The mock retains a decision before delaying, exposing remote-outcome ambiguity. See [incident exercise](INCIDENT_WALKTHROUGH.md) for local controls. Network tests also cover 429, 500, 400/permanent failures, invalid response shape/body and bounded response size. Kafka failures leave pending outbox rows; malformed event/dedup/version tests protect read effects.

## Load testing

```sh
python3 scripts/load_test.py --count 100 --concurrency 4
python3 scripts/load_test.py --count 1000 --concurrency 8
python3 scripts/load_test.py --count 10000 --concurrency 16
```

The workload measures acceptance only, not end-to-end settlement throughput. It reports elapsed time, attempted/successful throughput, p50/p95/p99 and errors. Use an isolated local dataset and watch database saturation. Real capacity testing needs realistic data sizes, production-like topology, dependency latency, warm-up, sustained load, failure/recovery periods and repeatable hardware. No local result is a production guarantee.

## Frontend and Compose

The frontend build proves bundling; a real browser test proves visible routes, login, data fetching, interactions and errors. Start the application, then run from `frontend/`:

```sh
npx playwright install chromium
npm run test:browser
```

The persistent browser test uses `http://127.0.0.1:5173` by default and reads generated local credentials from the project's ignored `.env`, or accepts `BROWSER_USERNAME` / `BROWSER_PASSWORD`. `BROWSER_BASE_URL` selects another loopback preview. A system Chromium can be selected through `BROWSER_EXECUTABLE_PATH`; `BROWSER_NO_SANDBOX=true` is an explicit setting for constrained cloud test environments. The test exercises a real synthetic payment through settlement/reconciliation, exception investigation, read-only assistance and knowledge retrieval at desktop/mobile widths. `BROWSER_SCREENSHOT_DIR` chooses a local screenshot directory.

Use screenshots plus API evidence to distinguish real data from hardcoded presentation. Compose config validation proves syntax/interpolation, not successful image build or service startup. Record build/up/health/demo separately.

CI runs the independent Python/JavaScript checks. The original root Java project remains unchanged; these are separate commands and neither project's success is a claim about the other. [VERIFICATION](VERIFICATION.md) records actual execution rather than proposed checks.
