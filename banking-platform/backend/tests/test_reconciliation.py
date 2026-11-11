from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.errors import DomainError
from app.exceptions import OperationalExceptionService
from app.models import BankAccount, Customer, FinancialTransaction
from app.reconciliation import (
    ExternalEvidence,
    ExternalReconciliationRecord,
    InternalEvidence,
    ReconciliationRun,
    ReconciliationService,
    compare_records,
)

DAY = date(2026, 11, 8)


def internal(reference="DEMO-PAY-1", amount=50000, currency="USD", status="SETTLED"):
    return InternalEvidence(uuid4(), reference, amount, currency, status, DAY, 6)


def external(reference="DEMO-PAY-1", amount=50000, currency="USD", status="SETTLED", day=DAY, received=DAY):
    return ExternalEvidence(uuid4(), reference, amount, currency, status, day, received)


@pytest.mark.parametrize(
    "ours,theirs,expected,variance",
    [
        ([internal()], [external()], ("MATCHED",), 0),
        ([internal()], [external(amount=45000)], ("AMOUNT_MISMATCH",), 5000),
        ([internal()], [], ("MISSING_EXTERNAL",), 50000),
        ([], [external()], ("MISSING_INTERNAL",), -50000),
        ([internal()], [external(currency="EUR")], ("CURRENCY_MISMATCH",), 50000),
        ([internal()], [external(), external()], ("DUPLICATE_EXTERNAL", "AMOUNT_MISMATCH"), -50000),
        ([internal()], [external(received=DAY + timedelta(days=1))], ("LATE_ARRIVAL",), 0),
        (
            [internal()],
            [external(day=DAY + timedelta(days=1), received=DAY + timedelta(days=1))],
            ("LATE_ARRIVAL",),
            50000,
        ),
        ([internal(status="CLEARED")], [external()], ("STATUS_MISMATCH",), 0),
        ([internal()], [external(status="FAILED")], ("STATUS_MISMATCH",), 0),
        ([internal(amount=-50000)], [external(amount=-50000)], ("MATCHED",), 0),
    ],
)
def test_reconciliation_classifies_evidence(ours, theirs, expected, variance):
    result = compare_records(ours, theirs, DAY, "USD")
    assert len(result) == 1
    assert result[0].classifications == expected
    assert result[0].variance_minor == variance


def test_multiple_anomalies_and_foreign_currency_never_summed():
    result = compare_records(
        [internal()], [external(amount=45000, status="FAILED"), external(currency="EUR")], DAY, "USD"
    )[0]
    assert result.classifications == (
        "DUPLICATE_EXTERNAL",
        "CURRENCY_MISMATCH",
        "AMOUNT_MISMATCH",
        "STATUS_MISMATCH",
    )
    assert result.external_amount_minor == 45000
    assert result.variance_minor == 5000
    assert compare_records([], [external(currency="EUR")], DAY, "USD") == []


def test_comparison_is_deterministic_and_internal_duplicates_are_control_violation():
    ours = [internal(reference="DEMO-B"), internal(reference="DEMO-A")]
    theirs = [external(reference="DEMO-B"), external(reference="DEMO-A", amount=45000)]
    assert compare_records(ours, theirs, DAY, "USD") == compare_records(ours[::-1], theirs[::-1], DAY, "USD")
    assert [r.external_reference for r in compare_records(ours, theirs, DAY, "USD")] == ["DEMO-A", "DEMO-B"]
    with pytest.raises(DomainError, match="Duplicate internal"):
        compare_records([internal(), internal()], [], DAY, "USD")


def seed_transaction(
    factory, *, amount=50000, reference="DEMO-PAY-1", currency="USD", transaction_type="CARD_PURCHASE"
):
    with factory.begin() as session:
        customer = Customer(
            external_reference="DEMO-CUSTOMER-" + str(uuid4()), display_name="Synthetic Customer"
        )
        session.add(customer)
        session.flush()
        account = BankAccount(
            customer_id=customer.id, account_reference="DEMO-ACCOUNT-" + str(uuid4()), currency=currency
        )
        session.add(account)
        session.flush()
        tx = FinancialTransaction(
            external_reference=reference,
            transaction_type=transaction_type,
            amount_minor=amount,
            currency=currency,
            source_account_id=account.id,
            counterparty_reference="DEMO-MERCHANT",
            status="SETTLED",
            business_date=DAY,
            version=6,
        )
        session.add(tx)
        session.flush()
        return tx.id


def evidence_body(amount=45000):
    return {
        "sourceReference": "DEMO-SETTLEMENT-2026-11-08",
        "records": [
            {
                "externalReference": "DEMO-PAY-1",
                "amountMinor": amount,
                "currency": "USD",
                "status": "SETTLED",
                "businessDate": DAY.isoformat(),
            }
        ],
    }


def test_run_snapshots_variance_exception_dedup_and_audited_resolution(factory):
    tx_id = seed_transaction(factory)
    recon = ReconciliationService(factory)
    first_import = recon.import_records(evidence_body())
    assert first_import["duplicateImport"] is False
    assert recon.import_records(evidence_body()) == {**first_import, "duplicateImport": True}
    run = recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    assert (run["recordsProcessed"], run["recordsMatched"], run["recordsUnmatched"]) == (1, 0, 1)
    assert (run["totalInternalMinor"], run["totalExternalMinor"], run["varianceMinor"]) == (
        50000,
        45000,
        5000,
    )
    result = recon.mismatches(run["id"])["items"][0]
    assert result["classifications"] == ["AMOUNT_MISMATCH"]
    assert result["transactionId"] == str(tx_id)
    assert recon.get_result(result["id"]) == result
    ops = OperationalExceptionService(factory)
    issue = ops.list()["items"][0]
    assert issue["reconciliationResultId"] == result["id"]
    with pytest.raises(DomainError, match="investigate"):
        ops.update(
            issue["id"],
            {
                "status": "RESOLVED",
                "assignedTeam": "PAYMENTS_OPS",
                "resolutionNotes": "Checked",
                "version": 0,
            },
        )
    investigating = ops.update(
        issue["id"],
        {
            "status": "INVESTIGATING",
            "assignedTeam": "PAYMENTS_OPS",
            "resolutionNotes": "Investigating external record",
            "version": 0,
        },
    )
    assert investigating["version"] == 1
    with pytest.raises(DomainError, match="another operator"):
        ops.update(issue["id"], {"status": "INVESTIGATING", "assignedTeam": "PAYMENTS_OPS", "version": 0})
    with pytest.raises(DomainError, match="notes"):
        ops.update(issue["id"], {"status": "RESOLVED", "assignedTeam": "PAYMENTS_OPS", "version": 1})
    resolved = ops.update(
        issue["id"],
        {
            "status": "RESOLVED",
            "assignedTeam": "PAYMENTS_OPS",
            "resolutionNotes": "Synthetic evidence verified; disposition recorded without money mutation.",
            "version": 1,
        },
    )
    assert resolved["status"] == "RESOLVED"
    assert [row["newStatus"] for row in ops.history(issue["id"])["items"]] == [
        "OPEN",
        "INVESTIGATING",
        "RESOLVED",
    ]
    rerun = recon.rerun(run["id"])
    assert rerun["previousRunId"] == run["id"]
    assert rerun["varianceMinor"] == 5000
    assert ops.list()["total"] == 1
    assert ops.get(issue["id"])["status"] == "RESOLVED"
    with factory() as session:
        assert session.get(FinancialTransaction, tx_id).amount_minor == 50000
        assert session.get(FinancialTransaction, tx_id).status == "SETTLED"
        assert session.scalar(select(func.count()).select_from(ExternalReconciliationRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ReconciliationRun)) == 2
    assert recon.get_run(run["id"]) == run


def test_currency_mismatch_is_explicit_without_cross_currency_arithmetic(factory):
    seed_transaction(factory)
    body = evidence_body()
    body["records"][0]["currency"] = "EUR"
    recon = ReconciliationService(factory)
    recon.import_records(body)
    run = recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    assert (run["totalInternalMinor"], run["totalExternalMinor"], run["varianceMinor"]) == (50000, 0, 50000)
    assert recon.mismatches(run["id"])["items"][0]["classifications"] == ["CURRENCY_MISMATCH"]


def test_duplicate_rows_preserved_but_identical_import_retry_is_not(factory):
    seed_transaction(factory)
    body = evidence_body(50000)
    body["records"] *= 2
    recon = ReconciliationService(factory)
    assert recon.import_records(body)["accepted"] == 2
    assert recon.import_records(body)["duplicateImport"]
    run = recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    assert run["totalExternalMinor"] == 100000
    assert recon.mismatches(run["id"])["items"][0]["classifications"] == [
        "DUPLICATE_EXTERNAL",
        "AMOUNT_MISMATCH",
    ]


def test_api_contract_problem_details_and_reader_boundary(factory, client, monkeypatch):
    seed_transaction(factory)
    # Shared fixture defaults to loopback demo; enable explicit API roles for this check.
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_API_USERNAME", "operator")
    monkeypatch.setenv("APP_API_PASSWORD", "synthetic-test-password")
    monkeypatch.setenv("APP_READONLY_USERNAME", "reader")
    monkeypatch.setenv("APP_READONLY_PASSWORD", "synthetic-read-password")
    reader = ("reader", "synthetic-read-password")
    operator = ("operator", "synthetic-test-password")
    assert (
        client.post("/api/reconciliation/external-records", json=evidence_body(), auth=reader).status_code
        == 403
    )
    assert (
        client.post("/api/reconciliation/external-records", json=evidence_body(), auth=operator).status_code
        == 201
    )
    assert (
        client.post("/api/reconciliation/external-records", json=evidence_body(), auth=operator).status_code
        == 200
    )
    created = client.post(
        "/api/reconciliation/runs", json={"businessDate": str(DAY), "currency": "USD"}, auth=operator
    )
    assert created.status_code == 201
    assert created.json()["varianceMinor"] == 5000
    run_id = created.json()["id"]
    assert client.get(f"/api/reconciliation/runs/{run_id}/mismatches", auth=reader).json()["total"] == 1
    invalid_page = client.get(
        f"/api/reconciliation/runs/{run_id}/mismatches?size=101",
        auth=reader,
        headers={"X-Request-ID": "recon-test"},
    )
    assert invalid_page.status_code == 422
    assert invalid_page.json()["requestId"] == "recon-test"
    assert client.get("/api/exceptions", auth=reader).json()["total"] == 1
    issue_id = client.get("/api/exceptions", auth=reader).json()["items"][0]["id"]
    assert (
        client.patch(
            f"/api/exceptions/{issue_id}",
            json={"status": "INVESTIGATING", "assignedTeam": "PAYMENTS_OPS", "version": 0},
            auth=reader,
        ).status_code
        == 403
    )
    assert client.get(f"/api/reconciliation/runs/{uuid4()}", auth=reader).status_code == 404
    malformed = evidence_body()
    malformed["records"][0]["amountMinor"] = 45.5
    assert (
        client.post("/api/reconciliation/external-records", json=malformed, auth=operator).status_code == 422
    )


@pytest.mark.postgres
def test_postgres_exception_cas_has_one_winner_and_one_audit_append(postgres_factory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy import inspect

    from app.exceptions import OperationalExceptionHistory

    seed_transaction(postgres_factory)
    recon = ReconciliationService(postgres_factory)
    recon.import_records(evidence_body())
    run = recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    assert run["varianceMinor"] == 5000
    service = OperationalExceptionService(postgres_factory)
    issue = service.list()["items"][0]
    barrier = Barrier(2)

    def investigate(team):
        barrier.wait(timeout=5)
        try:
            return service.update(
                issue["id"], {"status": "INVESTIGATING", "assignedTeam": team, "version": 0}
            )["version"]
        except DomainError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(investigate, ["OPS_A", "OPS_B"]))
    assert sorted(outcomes) == [1, 409]
    assert service.get(issue["id"])["version"] == 1
    assert service.history(issue["id"])["total"] == 2
    with postgres_factory() as session:
        indexes = inspect(session.connection()).get_indexes("operational_exception")
        assert "ix_exception_status_created" in {row["name"] for row in indexes}
        assert session.scalar(select(func.count()).select_from(OperationalExceptionHistory)) == 2


@pytest.mark.postgres
def test_postgres_concurrent_runs_deduplicate_identical_exception_evidence(postgres_factory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.exceptions import OperationalException

    seed_transaction(postgres_factory)
    service = ReconciliationService(postgres_factory)
    service.import_records(evidence_body())
    barrier = Barrier(2)

    def reconcile(_):
        barrier.wait(timeout=5)
        return service.create_run({"businessDate": str(DAY), "currency": "USD"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = list(executor.map(reconcile, range(2)))
    assert len({run["id"] for run in runs}) == 2
    assert all(run["varianceMinor"] == 5000 for run in runs)
    with postgres_factory() as session:
        assert session.scalar(select(func.count()).select_from(ReconciliationRun)) == 2
        assert session.scalar(select(func.count()).select_from(OperationalException)) == 1


@pytest.mark.parametrize(
    "external_amount,expected_batch_status", [(50000, "RECONCILED"), (45000, "CONFIRMED")]
)
def test_batch_is_reconciled_only_after_every_item_matches(factory, external_amount, expected_batch_status):
    from app.clearing import ClearingService
    from app.settlement import SettlementService
    from app.transactions import TransactionService

    tx_service = TransactionService(factory)
    customer = tx_service.create_customer(
        {"externalReference": "DEMO-C-RECON", "displayName": "Synthetic Customer"}
    )
    account = tx_service.create_account(
        {"customerId": customer["id"], "accountReference": "DEMO-A-RECON", "currency": "USD"}
    )
    tx, _ = tx_service.create(
        {
            "externalReference": "DEMO-PAY-1",
            "transactionType": "CARD_PURCHASE",
            "amountMinor": 50000,
            "currency": "USD",
            "sourceAccountId": account["id"],
            "counterpartyReference": "DEMO-MERCHANT",
            "businessDate": str(DAY),
        },
        "recon-match",
    )
    tx_service.authorize(tx["id"])
    tx_service.capture(tx["id"])
    ClearingService(factory).create(
        {
            "transactionId": tx["id"],
            "networkReference": "DEMO-CLEAR-1",
            "amountMinor": 50000,
            "currency": "USD",
            "businessDate": str(DAY),
        }
    )
    settlement = SettlementService(factory)
    batch = settlement.create({"businessDate": str(DAY), "currency": "USD"})
    for action in (settlement.ready, settlement.submit, settlement.confirm):
        batch = action(
            batch["id"], {"expectedVersion": batch["version"], "reason": "Synthetic settlement confirmation"}
        )
    recon = ReconciliationService(factory)
    recon.import_records(evidence_body(external_amount))
    run = recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    assert settlement.get(batch["id"])["status"] == expected_batch_status
    assert run["recordsMatched"] == int(external_amount == 50000)
    if expected_batch_status == "RECONCILED":
        assert settlement.history(batch["id"])["items"][-1]["newStatus"] == "RECONCILED"


def test_external_evidence_preserves_known_nonsettlement_transaction_identity(factory):
    """A record in an unexpected lifecycle state is known, not missing internal data."""
    from app.transactions import TransactionService

    service = TransactionService(factory)
    customer = service.create_customer({"externalReference": "DEMO-STATE-C", "displayName": "Synthetic"})
    account = service.create_account(
        {"customerId": customer["id"], "accountReference": "DEMO-STATE-A", "currency": "USD"}
    )
    states = (("RECEIVED", 100), ("AUTHORIZED", 101), ("DECLINED", 13), ("REVERSED", 102))
    transactions = []
    for state, amount in states:
        tx, _ = service.create(
            {
                "externalReference": f"DEMO-STATE-{state}",
                "transactionType": "CARD_PURCHASE",
                "amountMinor": amount,
                "currency": "USD",
                "sourceAccountId": account["id"],
                "counterpartyReference": "DEMO-MERCHANT",
                "businessDate": str(DAY),
            },
            f"state:{state}",
        )
        if state != "RECEIVED":
            service.authorize(tx["id"])
        if state == "REVERSED":
            service.reverse(tx["id"], "Synthetic lifecycle discrepancy")
        transactions.append((tx, state))
    recon = ReconciliationService(factory)
    # Unsettled instructions without external evidence remain outside missing-external checks.
    assert recon.create_run({"businessDate": str(DAY), "currency": "USD"})["recordsProcessed"] == 0
    recon.import_records(
        {
            "records": [
                {
                    "externalReference": tx["externalReference"],
                    "amountMinor": tx["amountMinor"],
                    "currency": "USD",
                    "status": "SETTLED",
                    "businessDate": str(DAY),
                }
                for tx, _ in transactions
            ]
        }
    )
    run = recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    assert (run["recordsProcessed"], run["recordsMatched"], run["varianceMinor"]) == (4, 0, 0)
    assert run["totalInternalMinor"] == run["totalExternalMinor"] == 316
    results = {row["externalReference"]: row for row in recon.mismatches(run["id"])["items"]}
    for tx, state in transactions:
        result = results[tx["externalReference"]]
        assert result["transactionId"] == tx["id"]
        assert result["internalStatus"] == state
        assert result["classifications"] == ["STATUS_MISMATCH"]
    assert sum(row["varianceMinor"] for row in results.values()) == run["varianceMinor"]


def test_known_foreign_currency_evidence_links_transaction_without_amount_comparison(factory):
    tx_id = seed_transaction(factory, currency="EUR")
    recon = ReconciliationService(factory)
    recon.import_records(evidence_body(45000))
    run = recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    result = recon.mismatches(run["id"])["items"][0]
    assert result["transactionId"] == str(tx_id)
    assert result["classifications"] == ["CURRENCY_MISMATCH"]
    assert result["internalAmountMinor"] is None
    assert (run["totalInternalMinor"], run["totalExternalMinor"], run["varianceMinor"]) == (0, 45000, -45000)


def test_known_other_date_transaction_is_late_evidence_not_missing_internal(factory):
    tx_id = seed_transaction(factory)
    with factory.begin() as session:
        session.get(FinancialTransaction, tx_id).business_date = DAY - timedelta(days=1)
    recon = ReconciliationService(factory)
    recon.import_records(evidence_body(50000))
    run = recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    result = recon.mismatches(run["id"])["items"][0]
    assert result["transactionId"] == str(tx_id)
    assert result["classifications"] == ["LATE_ARRIVAL"]
    assert result["internalAmountMinor"] is None
    assert result["varianceMinor"] == run["varianceMinor"] == -50000


def test_reconciliation_database_outage_remains_operational_error(factory, monkeypatch):
    from sqlalchemy.exc import OperationalError

    recon = ReconciliationService(factory)
    outage = OperationalError("database connection", {}, RuntimeError("synthetic connection failure"))
    calls = []

    def fail(*args):
        calls.append(True)
        raise outage

    monkeypatch.setattr(recon, "_create_run", fail)
    with pytest.raises(OperationalError) as error:
        recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    assert error.value is outage
    assert len(calls) == 1


def test_reconciliation_exhausted_serialization_retries_are_conflicts(factory, monkeypatch):
    from sqlalchemy.exc import OperationalError

    class SerializationFailure(Exception):
        sqlstate = "40001"

    recon = ReconciliationService(factory)
    calls = []

    def fail(*args):
        calls.append(True)
        raise OperationalError("database serialization", {}, SerializationFailure())

    monkeypatch.setattr(recon, "_create_run", fail)
    with pytest.raises(DomainError) as error:
        recon.create_run({"businessDate": str(DAY), "currency": "USD"})
    assert error.value.status == 409
    assert len(calls) == 3
