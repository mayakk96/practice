# API and demo guide

All examples use synthetic data and the unauthenticated loopback demo. Secured Compose requires HTTP Basic; add `--user operator` to curl so it prompts for the generated password. Do not paste a password into source or shared shell history. `/docs` is the generated OpenAPI UI and `/openapi.json` is the machine-readable contract; authenticated deployments protect these routes too.

## Endpoint map

| Method | Route | Purpose |
| --- | --- | --- |
| POST / GET | `/api/customers`, `/api/accounts` | Create/list synthetic records |
| POST / GET | `/api/transactions` | Submit an idempotent instruction / bounded list |
| GET | `/api/transactions/by-reference/{reference}` | External reference lookup |
| GET | `/api/transactions/{id}` | Current aggregate |
| GET | `/api/transactions/{id}/history`, `/ledger` | Ordered history / journal entries |
| POST | `/api/transactions/{id}/authorize`, `/capture` | Explicit lifecycle commands |
| POST | `/api/transactions/{id}/reverse`, `/refund` | Audited compensation/full child refund |
| POST / GET | `/api/clearing/records` | Confirm or list clearing |
| POST | `/api/clearing/import` | Multipart CSV import |
| GET | `/api/clearing/{id}` | Clearing record |
| GET | `/api/clearing/imports/{id}`, `/rows` | Summary and row outcomes |
| POST / GET | `/api/settlements` | Create bounded batch / list batches |
| GET | `/api/settlements/{id}`, `/items`, `/history` | Batch and evidence |
| POST | `/api/settlements/{id}/ready`, `/submit`, `/confirm` | Versioned batch commands |
| POST | `/api/reconciliation/external-records` | Ingest independent evidence |
| POST / GET | `/api/reconciliation/runs` | Start run / list snapshots |
| GET | `/api/reconciliation/runs/{id}`, `/mismatches` | Run and mismatches |
| POST | `/api/reconciliation/runs/{id}/rerun` | New linked snapshot |
| GET | `/api/reconciliation/results/{id}` | Individual result evidence |
| GET / PATCH | `/api/exceptions/{id}` | Read / versioned work-item update |
| GET | `/api/exceptions`, `/api/exceptions/{id}/history` | Bounded work queue / audit |
| GET | `/api/analytics/daily`, `/transactions`, `/settlement`, `/exceptions` | Explicit-source read model |
| POST | `/api/knowledge/search` | Read-only bounded runbook retrieval |
| GET | `/api/assistant/exceptions/{id}` | Read-only incident explanation |
| POST | `/mcp/` | Official SDK stateless MCP transport |
| GET | `/health`, `/health/readiness`, `/health/liveness`, `/metrics` | Operational signals |

Collection endpoints accept `page>=0` and `1<=size<=100`, default 20. Analytics accepts optional `businessDate`/`currency` where relevant. Work queues support their documented status filters. Each page returns `items`, `page`, `size`, `total`; analytics adds source/backlog metadata.

## Complete manual payment flow

Create a customer, then replace `CUSTOMER_UUID` below with its returned `id`:

```sh
curl -i http://127.0.0.1:8080/api/customers -H 'Content-Type: application/json' \
  -d '{"externalReference":"DEMO-CUSTOMER-MANUAL","displayName":"Synthetic Customer"}'
curl -i http://127.0.0.1:8080/api/accounts -H 'Content-Type: application/json' \
  -d '{"customerId":"CUSTOMER_UUID","accountReference":"DEMO-ACCOUNT-MANUAL","currency":"USD"}'
```

Replace `ACCOUNT_UUID` with its returned `id`:

```sh
curl -i http://127.0.0.1:8080/api/transactions \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: manual-payment-001' \
  -d '{"externalReference":"DEMO-MANUAL-PAYMENT-001","transactionType":"CARD_PURCHASE","amountMinor":50000,"currency":"USD","sourceAccountId":"ACCOUNT_UUID","counterpartyReference":"DEMO-MERCHANT","businessDate":"2026-11-08"}'
```

A new instruction returns 201. Repeat the same body/key and expect200 with the original transaction. Change `amountMinor` under the same key and expect409. Store the returned transaction `id` as `TX_UUID` for subsequent commands:

```sh
curl -i -X POST http://127.0.0.1:8080/api/transactions/TX_UUID/authorize
curl -i -X POST http://127.0.0.1:8080/api/transactions/TX_UUID/capture
curl http://127.0.0.1:8080/api/transactions/TX_UUID/history
curl http://127.0.0.1:8080/api/transactions/TX_UUID/ledger
```

Use the authorized response's `networkReference` as `NETWORK_REFERENCE`:

```sh
curl -i http://127.0.0.1:8080/api/clearing/records -H 'Content-Type: application/json' \
  -d '{"transactionId":"TX_UUID","networkReference":"NETWORK_REFERENCE","amountMinor":50000,"currency":"USD","businessDate":"2026-11-08"}'
curl -i http://127.0.0.1:8080/api/settlements -H 'Content-Type: application/json' \
  -d '{"businessDate":"2026-11-08","currency":"USD","maxItems":100}'
```

Use `BATCH_UUID` and the current returned `version`; a fresh batch begins version 0:

```sh
curl -i http://127.0.0.1:8080/api/settlements/BATCH_UUID/ready -H 'Content-Type: application/json' \
  -d '{"expectedVersion":0,"reason":"Synthetic batch reviewed"}'
curl -i http://127.0.0.1:8080/api/settlements/BATCH_UUID/submit -H 'Content-Type: application/json' \
  -d '{"expectedVersion":1,"reason":"Synthetic submission recorded"}'
curl -i http://127.0.0.1:8080/api/settlements/BATCH_UUID/confirm -H 'Content-Type: application/json' \
  -d '{"expectedVersion":2,"reason":"Synthetic external confirmation received"}'
```

Confirmation is a local operator assertion in this educational application. It does not send money to an actual payment network. Never infer an external settlement guarantee from this marker alone.

## Reconciliation and exception investigation

```sh
curl -i http://127.0.0.1:8080/api/reconciliation/external-records -H 'Content-Type: application/json' \
  -d '{"sourceReference":"DEMO-MANUAL-FILE","records":[{"externalReference":"DEMO-MANUAL-PAYMENT-001","amountMinor":45000,"currency":"USD","status":"SETTLED","businessDate":"2026-11-08","receivedDate":"2026-11-08"}]}'
curl -i http://127.0.0.1:8080/api/reconciliation/runs -H 'Content-Type: application/json' \
  -d '{"businessDate":"2026-11-08","currency":"USD"}'
curl 'http://127.0.0.1:8080/api/reconciliation/runs/RUN_UUID/mismatches?page=0&size=20'
curl 'http://127.0.0.1:8080/api/exceptions?page=0&size=20'
curl http://127.0.0.1:8080/api/assistant/exceptions/EXCEPTION_UUID
```

An isolated run returns `totalInternalMinor:50000`, `totalExternalMinor:45000`, `varianceMinor:5000`. The result contains `classifications:["AMOUNT_MISMATCH"]`. Other records on the same date/currency legitimately enlarge a run.

Read the exception's current `version` before updating it:

```sh
curl -i -X PATCH http://127.0.0.1:8080/api/exceptions/EXCEPTION_UUID -H 'Content-Type: application/json' \
  -d '{"status":"INVESTIGATING","assignedTeam":"PAYMENTS_OPS","resolutionNotes":"Comparing original synthetic source records.","version":0}'
curl -i -X PATCH http://127.0.0.1:8080/api/exceptions/EXCEPTION_UUID -H 'Content-Type: application/json' \
  -d '{"status":"RESOLVED","assignedTeam":"PAYMENTS_OPS","resolutionNotes":"Investigation outcome recorded; any financial correction follows its separate controlled workflow.","version":1}'
```

A stale version returns409. Closing the work item leaves financial state and original reconciliation evidence intact.

## Clearing CSV

```sh
curl -i http://127.0.0.1:8080/api/clearing/import -F 'file=@demo/data/clearing-template.csv'
```

The exact header is `transactionId,networkReference,amountMinor,currency,businessDate`. Replace template IDs with actual captured transactions. UTF-8 files are limited to 1 MiB and 10,000 data rows. A file transaction uses a savepoint per row, retains accepted/rejected/duplicate outcomes and commits the summary atomically. Schema-invalid files fail; malformed rows are retained as rejections. The exact file bytes produce a SHA256 duplicate-file identity. Full CSV multiline fields are intentionally unsupported and rejected.

## Refund and reversal

`POST /api/transactions/{id}/reverse` accepts `{"reason":"Synthetic cancellation"}` only before clearing. Captured reversal appends compensation. A settled original can create one full refund child:

```sh
curl -i http://127.0.0.1:8080/api/transactions/TX_UUID/refund \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: manual-refund-001' \
  -d '{"reason":"Synthetic full refund"}'
```

The returned child starts RECEIVED and must be authorized, captured, cleared and settled. Refund settlement is a credit with a negative net contribution; external evidence uses the negative amount. Partial/multiple refunds are outside scope.

## Runbooks, errors and local failure demos

```sh
curl http://127.0.0.1:8080/api/knowledge/search -H 'Content-Type: application/json' \
  -d '{"query":"How should a network timeout be investigated?","topK":3}'
python3 scripts/demo_duplicate_transaction.py
python3 scripts/demo_reconciliation_mismatch.py --run-id fresh-mismatch-demo
python3 scripts/demo_network_timeout.py
python3 scripts/load_test.py --count 1000 --concurrency 8
```

The timeout script expects a separately configured timeout mock; see [incident exercise](INCIDENT_WALKTHROUGH.md). It deliberately fails if authorization unexpectedly succeeds. Load 100/1000/10000 is optional and does not run during ordinary unit tests.

Problem Details contain `type`, `title`, `status`, `detail`, `requestId`, and responses return `X-Request-ID`. Invalid fields use422; invalid query/business inputs may use400; missing records404; state/uniqueness/version conflicts409; rejected/malformed network responses502; exhausted transient network/database availability503. Credentials/SQL/provider bodies are not response evidence.
