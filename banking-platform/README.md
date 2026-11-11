# Enterprise Banking Transaction & Reconciliation Platform

An independent educational Python backend and JavaScript operations console for tracing synthetic payments from receipt to authorization, capture, clearing, settlement, reconciliation and investigation. The original Java onboarding project in the repository root remains a separate project; this application lives entirely in `banking-platform/`.

**This is fictional portfolio work. It contains no employer code, customer data, real account numbers or production secrets and has no affiliation with Discover, PULSE, BNY Mellon, FIS or any previous or prospective employer. It has not been deployed as a bank's production software.**

![Operations console showing synthetic PostgreSQL data and Kafka projections](docs/images/dashboard-desktop.png)

## Why this project exists

A payment is more than a row with a changing status. A duplicate instruction can duplicate money movement; a timeout can conceal a successful downstream decision; a successful database commit can precede a failed Kafka publish; and settlement totals can disagree even when the API returned success. This project makes those boundaries inspectable in code, tests and demonstrations.

## Architecture

```mermaid
flowchart LR
  UI[React operations console] --> API[FastAPI REST]
  MCP[Read-only MCP client] --> Read[Banking services and bounded evidence]
  API --> Services[Transactions / Clearing / Settlement / Reconciliation]
  Read --> Services
  Services --> PG[(PostgreSQL)]
  Services --> Network[Fictional HTTP payment network]
  PG --> Outbox[Outbox dispatcher]
  Outbox --> Kafka[Kafka banking.events.v1]
  Kafka --> Projection[Deduplicating analytics consumer]
  Projection --> PG
  Runbooks[Synthetic runbooks] --> Read
```

This is a **modular monolith**, plus a mock external service and infrastructure. FastAPI adapters delegate to service functions; SQLAlchemy transactions own business state, journal/history and outbox writes. Alembic migrations define the schema. The read model is updated by Kafka consumption when events are enabled. The local no-broker mode identifies its write-model analytics source explicitly.

## Banking transaction lifecycle

```text
RECEIVED → VALIDATED → AUTHORIZED → CAPTURED → CLEARED → SETTLED
                          │             │                  │
                          └─ REVERSED ──┘                  └─ full REFUND child
               VALIDATED → DECLINED
```

Submission validates and records a transaction; authorization calls the network through a bounded adapter. Capture creates a balanced journal. Clearing validates confirmed details before settlement membership. Settlement confirmation creates its journal movements. Reconciliation compares independent external evidence with internal settled transactions. A discrepancy creates an operational exception, whose resolution records an operator explanation without altering money.

## Core capabilities

- Synthetic customers and accounts; `CARD_PURCHASE`, `ACCOUNT_TRANSFER` and full `REFUND` child transactions.
- Mandatory submission `Idempotency-Key`, normalized request hashes and unique database claims; same-key conflict detection and concurrent replay recovery.
- Explicit state transitions with versioned history, actor, timestamp and request correlation ID.
- Structurally balanced paired debit/credit journals; append-only corrections through reversal/refund rather than balance rewrites.
- Validated JSON/CSV clearing, duplicate file detection and retained row outcomes.
- Single-currency settlement batches with one membership per transaction and audited commands.
- Deterministic reconciliation snapshots, multiple mismatch classifications and version-checked exception investigation.
- At-least-once outbox publication, idempotent event handling, out-of-order projection protection and operational analytics.
- Read-only MCP, lexical RAG and a bounded incident explanation grounded in stored evidence/runbooks.

## Technology stack

| Layer | Implementation |
| --- | --- |
| Backend | Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2 |
| Database | PostgreSQL 17, Alembic; SQLite for disposable local demonstrations |
| Integration | HTTPX payment-network adapter, fictional Python mock |
| Events | Kafka, database outbox, deduplication and reporting projection |
| Frontend | JavaScript, React, Vite |
| Operations | JSON logs, request IDs, Prometheus metrics, health probes |
| Tests | pytest, real PostgreSQL integration/concurrency tests, Kafka tests, HTTP failure tests |
| AI boundary | Read-only MCP tools, bundled runbooks, feature-hash retrieval, default deterministic answers |

## Quick start

From this directory, use Docker with the Compose plugin and Python 3:

```sh
python3 scripts/create_env.py
docker compose up --build
```

The generated `.env` is ignored and contains local credentials; no values are printed. Open the console at `http://127.0.0.1:5173` and the API reference at `http://127.0.0.1:8080/docs`. Then run:

```sh
python3 scripts/demo_end_to_end.py
python3 scripts/demo_duplicate_transaction.py
```

Run the commands from `banking-platform/`, not the repository root: the root Compose/Maven project is independent.

## Demo mode without Docker

Install Python 3.12+ and Node.js 22+, then:

```sh
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -c requirements.lock -e '.[test]'
alembic upgrade head
APP_DEMO=true APP_AUTH_ENABLED=false uvicorn app.main:app --host 127.0.0.1 --port 8080
```

From the repository root, in another terminal:

```sh
cd banking-platform/frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Run `python3 scripts/demo_end_to_end.py --no-auth` from this directory. SQLite mode does not prove PostgreSQL row-lock behavior. Its on-disk `backend/banking-demo.db` persists until removed. Stop the local backend before removing only that demo file to reset it; run `alembic upgrade head` again. For a second independent dataset, pass a fresh `--run-id` instead of reusing the default identifiers.

## Docker environment

Compose provides PostgreSQL, Kafka, mock payment network, API, an outbox/analytics worker and the console. Health gates keep the API from starting before required infrastructure is ready. Credentials come from the ignored `.env`. Inspect health and logs with:

```sh
docker compose ps
docker compose logs -f app
docker compose down
```

`docker compose down -v` removes this project's local database volume and all demonstration data; use it only when intentionally resetting the demo. [Setup and API guide](docs/API_GUIDE.md) includes the complete HTTP flow.

## API examples

Requests below assume the loopback no-auth demo; with Compose, add `--user YOUR_OPERATOR_NAME` so curl prompts for the local password.

```sh
curl http://127.0.0.1:8080/api/customers -H 'Content-Type: application/json' \
  -d '{"externalReference":"DEMO-CUSTOMER-001","displayName":"Synthetic Customer"}'
# Use the returned customer UUID:
curl http://127.0.0.1:8080/api/accounts -H 'Content-Type: application/json' \
  -d '{"customerId":"CUSTOMER_UUID","accountReference":"DEMO-ACCOUNT-001","currency":"USD"}'
```

The [API guide](docs/API_GUIDE.md) documents submission, replay/conflict, authorization, capture, clearing, settlement, external evidence, reconciliation and exception investigation. Collection endpoints use bounded `page` and `size`; errors use Problem Details and `requestId`.

## Kafka/events

Business changes and banking outbox rows commit in one database transaction. A separate dispatcher publishes versioned events to `banking.events.v1`, using aggregate UUID keys. Kafka acknowledgement precedes the delivered marker, so a crash can cause a duplicate. Consumer event IDs and version guards protect projection effects. Ordering applies per keyed partition, not globally. Failed records have bounded retries and a dead-letter topic; operators inspect and replay corrected data deliberately. See [architecture](docs/ARCHITECTURE.md).

## Ledger

Amounts are integer minor units, never floating-point money. USD/EUR/GBP are the only supported currencies, all with two decimal places. Each journal row represents an equal debit and credit with one positive amount and currency; a database posting view exposes the two sides. This structure makes an unbalanced entry unrepresentable. The service and a composite database foreign key also require full-value journal money to match its transaction. Database triggers reject journal updates/deletes. Journals are history, not spendable-balance calculations or an overdraft authorization system. The console preserves large aggregate integers with `json-bigint` and formats money with `BigInt`. See [banking guide](docs/BANKING_DOMAIN_GUIDE.md).

## Settlement

Cleared transactions enter a bounded, single-currency batch. A unique transaction membership prevents double inclusion. The batch advances `OPEN → READY → SUBMITTED → CONFIRMED → RECONCILED`; explicit versions protect commands and all history is retained. Gross debit, gross credit and signed net amounts are deterministic. A matched reconciliation can mark an eligible confirmed batch reconciled.

## Reconciliation

The engine stores a snapshot for a business date and currency. Internal settled records are compared by external reference against independently ingested external evidence. Amount, currency, status, missing records, duplicate external rows and arrival timing remain visible; a rerun creates new evidence rather than overwriting an earlier run. `varianceMinor = totalInternalMinor - totalExternalMinor`, with signed refund treatment and no cross-currency arithmetic. See the [$500/$450 walkthrough](docs/RECONCILIATION_WALKTHROUGH.md).

## Exception management

Material mismatch results create operational exceptions. An operator moves `OPEN → INVESTIGATING → RESOLVED` with assignment, current version and required resolution notes. A stale version fails with `409`. Closing a case records an investigation outcome; it does not repair a ledger, authorize a payment or edit a reconciliation snapshot.

## Observability

`/health`, `/health/readiness`, `/health/liveness` and `/metrics` expose service health and Prometheus signals. JSON logs use request IDs and safe resource metadata. Outbox backlog/oldest age, network latency/failures, transaction activity, mismatch count and exception workload connect technical failures to banking impact. [Incident walkthrough](docs/INCIDENT_WALKTHROUGH.md) distinguishes example SLOs from measured results.

## Security

Compose uses environment-supplied HTTP Basic operator/reader credentials. Operators issue business commands; readers use read-only REST/MCP. No-auth mode is for loopback demonstrations. This is a teaching boundary; production needs TLS, centralized OIDC, object/tenant authorization, rate limits, managed secrets and independent review. No financial compliance certification is claimed.

## AI/MCP/RAG

The MCP tools retrieve sanitized transaction/history/batch/run/exception/analytics evidence and search runbooks. There are no model-facing settlement, reversal, authorization, balance-edit or exception-resolution tools. The incident assistant reports observed facts, possible explanations and suggested human checks with citations.

Bundled documents become chunks, feature-hash vectors, ranked passages and bounded evidence. Feature hashing is an educational **lexical baseline**, not a production semantic embedding model. The default explanation is deterministic; external model use is optional and disabled unless configured. Retrieved instructions are untrusted content, and citations do not prove a conclusion is correct. See [AI boundaries](docs/AI_AND_OPERATIONS.md).

## Testing

```sh
cd backend
pytest
ruff check app tests
# Start PostgreSQL and Kafka, then supply actual local connection values:
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5433/banking pytest -m postgres
KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9095 pytest -m kafka
cd ../frontend
npm ci
npm test
npm run build
cd ..
docker compose config --quiet
python3 scripts/demo_end_to_end.py
```

Environment variables in examples are placeholders; never put real secrets in source. [Testing strategy](docs/TESTING.md) explains which behaviors require PostgreSQL or a real broker. The final verification record reports commands actually executed separately from these local instructions.

## CI

The Python/JavaScript workflow compiles/imports Python, runs static checks and unit/API tests, exercises PostgreSQL/Kafka integration, builds the frontend and validates Compose. Reports support diagnosis. It builds and tests; it does not deploy this system.

## Design tradeoffs and production limitations

The implementation uses one relational database and a modular monolith, local Kafka, a simple dispatcher, HTTP Basic and bounded educational reconciliation. Network authorization is synchronous and can hold a row lock during a bounded remote call. Full single refunds are supported; partial refunds, FX, interest, real funding checks, real settlement rails and regulatory controls are outside scope. SQLite is useful for learning but is not a concurrency substitute for PostgreSQL. Local load numbers are not capacity guarantees. Hypothetical [AWS](docs/AWS_REFERENCE_ARCHITECTURE.md) and [multi-region](docs/MULTI_REGION_DESIGN.md) designs are documents, not deployed infrastructure.

## Interview resources

Start with [code walkthrough](docs/CODE_WALKTHROUGH.md), [transaction walkthrough](docs/TRANSACTION_WALKTHROUGH.md) and [reconciliation walkthrough](docs/RECONCILIATION_WALKTHROUGH.md). Then study the [128 interview questions](docs/INTERVIEW_GUIDE.md), [requirements translation](docs/BUSINESS_REQUIREMENTS.md), [incident narrative](docs/INCIDENT_WALKTHROUGH.md) and [review summary](docs/REVIEW_SUMMARY.md). Explain the actual code and its limits rather than presenting technology names as guarantees.

## Disclaimer

All customers, accounts, references, policies, transactions and operational examples are synthetic. This independent project uses publicly understood concepts and is not affiliated with any bank, payment network or employer. It does not claim professional deployment, production suitability or measured enterprise-scale performance.
