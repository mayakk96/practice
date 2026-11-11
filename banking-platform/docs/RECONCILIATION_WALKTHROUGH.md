# A USD 500.00 internal payment and USD 450.00 external record

All values are synthetic. The complete scenario is executable through `scripts/demo_end_to_end.py`. Money is represented as `50000` and `45000` minor units, so the difference is exactly `5000` USD minor units ($50.00); no floating-point rounding is involved.

## Inputs and snapshot

`ReconciliationService.import_records` in `backend/app/reconciliation.py` receives external records with upstream external reference, **signed** amount, currency, status, business date and received date. Source/import fingerprinting detects the same file-equivalent submission; distinct duplicate records remain available for duplicate classification rather than being silently collapsed.

The internal payment is already `SETTLED` after `SettlementService.confirm`. Its external reference identifies it across systems. `POST /api/reconciliation/runs` with `{"businessDate":"2026-11-08","currency":"USD"}` starts `ReconciliationService.create_run`. The service selects the relevant internal and external records, evaluates the pure reconciliation logic and stores `ReconciliationRun` plus `ReconciliationResult` snapshots. A later rerun is a new run: the first result remains evidence of what was compared at that time.

## Matching and classification

Matching uses the external transaction reference, not the database row order. For a unique internal and external candidate, the engine compares amount, currency, expected status and dates. It can retain multiple classifications for one reference; one difference must not hide another. Duplicate external evidence is reported explicitly. A missing internal or external candidate is distinct from an amount difference. Currency anomalies are visible but never added into another currency's monetary total.

For the default payment:

| Field | Internal | External |
| --- | --- | --- |
| Reference | `DEMO-portfolio-demo-mismatch` | Same reference |
| Currency | USD | USD |
| Status | SETTLED | SETTLED |
| Amount minor units | 50000 | 45000 |
| Result | AMOUNT_MISMATCH | Variance 5000 |

A second USD 100.00 payment matches exactly. The isolated demonstration's expected run totals are internal `60000`, external `55000`, variance `5000`. Additional data already present for the same date/currency can legitimately change the population. Use a reset database or a separate date for an isolated example.

Refund evidence uses negative amounts. A refund for USD 100.00 contributes `-10000`, rather than inflating outbound totals. The run is single-currency; EUR and GBP require separate runs.

## From discrepancy to operational exception

The mismatch result identifies the transaction/reference and both amounts/statuses. A material result creates or links an `OperationalException` through `OperationalExceptionService` in `backend/app/exceptions.py`. Its stable deduplication identity prevents every rerun from creating an endless queue of the same unresolved issue. The run/result remain immutable even when an operator later changes the work-item status.

```sh
curl http://127.0.0.1:8080/api/reconciliation/runs/RUN_UUID/mismatches?page=0\&size=20
curl http://127.0.0.1:8080/api/exceptions?page=0\&size=20
curl http://127.0.0.1:8080/api/exceptions/EXCEPTION_UUID/history
```

For secured Compose add operator/reader credentials through curl's prompt. Compare the internal transaction history, batch item, external source import and the affected references. The read-only assistant at `/api/assistant/exceptions/{id}` packages this evidence and relevant runbook citations; it does not settle a transaction or close the work item.

## Record investigation and resolution

An operator first reads the exception's current `version`, then sends:

```json
{"status":"INVESTIGATING","assignedTeam":"PAYMENTS_OPS","resolutionNotes":"Comparing synthetic source evidence with the confirmed batch.","version":0}
```

`PATCH /api/exceptions/{id}` verifies the state transition and performs a version-checked update. The returned version must be used for the next edit. A stale client receives `409`, preserving another analyst's notes. `RESOLVED` requires an explanation of the outcome. History retains the actor, time, request ID and notes.

Resolution does **not** overwrite 50000 with 45000, delete a journal or mark the evidence matched. A legitimate financial correction needs its own authorized workflow and append-only financial entry. If previously missing external evidence arrives, rerun reconciliation and retain the earlier run for audit. External evidence is append-only: importing a replacement for an existing reference creates duplicate evidence; this version has no supersession/amendment endpoint. Automatic correction, tolerance write-offs, multi-source netting and regulatory reporting are outside this teaching model.


The initial internal scope is clearing/settlement-eligible transactions. Any transaction referenced by external evidence is also loaded, so an external settled record for an internal received instruction retains the real transaction ID and becomes a status mismatch. Same-date, same-currency compared records contribute to snapshot totals; these are record-comparison totals, not ledger liabilities. Wrong-date/currency evidence remains visible without cross-currency arithmetic.
