"""Financial workflow tests run against schemas installed exclusively by Alembic."""

from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.clearing import ClearingImport, ClearingImportRow, ClearingRecord, ClearingService
from app.errors import DomainError
from app.models import FinancialTransaction, JournalEntry
from app.settlement import SettlementBatch, SettlementItem, SettlementService
from app.transactions import TransactionService

BUSINESS_DATE = "2026-11-08"


def captured(factory, amount=50000, currency="USD"):
    service = TransactionService(factory)
    customer = service.create_customer(
        {"externalReference": "DEMO-C-" + uuid4().hex, "displayName": "Synthetic Customer"}
    )
    account = service.create_account(
        {"customerId": customer["id"], "accountReference": "DEMO-A-" + uuid4().hex, "currency": currency}
    )
    transaction, _ = service.create(
        {
            "externalReference": "DEMO-T-" + uuid4().hex,
            "transactionType": "CARD_PURCHASE",
            "amountMinor": amount,
            "currency": currency,
            "sourceAccountId": account["id"],
            "counterpartyReference": "DEMO-MERCHANT",
            "businessDate": BUSINESS_DATE,
        },
        uuid4().hex,
    )
    service.authorize(transaction["id"])
    return service.capture(transaction["id"])


def clearing_body(transaction):
    return {
        "transactionId": transaction["id"],
        "networkReference": "CLEAR-" + transaction["id"],
        "amountMinor": transaction["amountMinor"],
        "currency": transaction["currency"],
        "businessDate": transaction["businessDate"],
    }


def clear(factory, transaction):
    return ClearingService(factory).create(clearing_body(transaction))


def settle(factory, transaction):
    clear(factory, transaction)
    service = SettlementService(factory)
    batch = service.create({"businessDate": transaction["businessDate"], "currency": transaction["currency"]})
    for action in (service.ready, service.submit, service.confirm):
        batch = action(batch["id"], {"expectedVersion": batch["version"], "reason": "Synthetic confirmation"})
    return batch


def test_clearing_replay_conflict_and_mismatch_do_not_change_financial_state(factory):
    transaction = captured(factory)
    service = ClearingService(factory)
    body = clearing_body(transaction)
    mismatched = {**body, "amountMinor": transaction["amountMinor"] - 1}
    with pytest.raises(DomainError) as error:
        service.create(mismatched)
    assert error.value.status == 409
    assert TransactionService(factory).get(transaction["id"])["status"] == "CAPTURED"
    created = service.create(body)
    replay = service.create(body)
    assert created["id"] == replay["id"]
    assert not created["duplicate"] and replay["duplicate"]
    with pytest.raises(DomainError):
        service.create({**body, "networkReference": "OTHER-REFERENCE"})
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ClearingRecord)) == 1
        assert (
            session.scalar(
                select(FinancialTransaction.status).where(FinancialTransaction.id == UUID(transaction["id"]))
            )
            == "CLEARED"
        )


def test_csv_every_row_audited_and_content_replay_returns_original_summary(factory):
    transaction = captured(factory)
    wrong = captured(factory, 10000)
    header = ",".join(ClearingService.HEADER)
    row = f"{transaction['id']},CLEAR-{transaction['id']},50000,USD,{BUSINESS_DATE}"
    content = (
        header
        + "\n"
        + row
        + "\n"
        + row
        + "\nnot-a-uuid,bad,5,USD,2026-11-08\n"
        + f"{wrong['id']},CLEAR-WRONG,9999,USD,{BUSINESS_DATE}\n"
    ).encode()
    service = ClearingService(factory)
    result = service.import_csv(content, "clearing.csv")
    assert (result["rowsReceived"], result["accepted"], result["rejected"], result["duplicates"]) == (
        4,
        1,
        2,
        1,
    )
    rows = service.import_rows(UUID(result["id"]))["items"]
    assert [row["status"] for row in rows] == ["ACCEPTED", "DUPLICATE", "REJECTED", "REJECTED"]
    replay = service.import_csv(content, "different-name.csv")
    assert replay["id"] == result["id"] and replay["duplicateFile"]
    assert TransactionService(factory).get(wrong["id"])["status"] == "CAPTURED"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ClearingImport)) == 1
        assert session.scalar(select(func.count()).select_from(ClearingImportRow)) == 4
        assert session.scalar(select(func.count()).select_from(ClearingRecord)) == 1


@pytest.mark.parametrize(
    "content",
    [b"", b"bad,header\n1,2", b"\xff", b"transactionId,networkReference,amountMinor,currency,businessDate\n"],
)
def test_invalid_csv_schema_rejected_before_creating_import(factory, content):
    with pytest.raises(DomainError) as error:
        ClearingService(factory).import_csv(content, "bad.csv")
    assert error.value.status == 400
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ClearingImport)) == 0


def test_csv_fractional_money_and_blank_records_are_rejected_explicitly(factory):
    transaction = captured(factory)
    header = ",".join(ClearingService.HEADER)
    content = (header + "\n" + f"{transaction['id']},CLEAR-FRACTION,50.25,USD,{BUSINESS_DATE}\n\n").encode()
    result = ClearingService(factory).import_csv(content, "fraction.csv")
    assert result["rowsReceived"] == 2 and result["rejected"] == 2 and result["accepted"] == 0
    assert TransactionService(factory).get(transaction["id"])["status"] == "CAPTURED"


def test_settlement_lifecycle_totals_and_repeated_confirmation_are_guarded(factory):
    first = captured(factory, 50000)
    second = captured(factory, 10000)
    euro = captured(factory, 20000, "EUR")
    for transaction in (first, second, euro):
        clear(factory, transaction)
    service = SettlementService(factory)
    batch = service.create({"businessDate": BUSINESS_DATE, "currency": "USD"})
    assert (
        batch["status"],
        batch["transactionCount"],
        batch["grossDebitMinor"],
        batch["grossCreditMinor"],
        batch["netSettlementMinor"],
    ) == ("OPEN", 2, 60000, 0, 60000)
    with pytest.raises(DomainError):
        service.confirm(batch["id"], {"expectedVersion": 0, "reason": "Cannot skip submission"})
    with pytest.raises(DomainError):
        service.create({"businessDate": BUSINESS_DATE, "currency": "USD"})
    for action in (service.ready, service.submit, service.confirm):
        batch = action(
            batch["id"], {"expectedVersion": batch["version"], "reason": "Fictional operator step"}
        )
    assert batch["status"] == "CONFIRMED" and batch["version"] == 3
    assert service.history(batch["id"])["total"] == 4
    assert [entry["newStatus"] for entry in service.history(batch["id"])["items"]] == [
        "OPEN",
        "READY",
        "SUBMITTED",
        "CONFIRMED",
    ]
    with pytest.raises(DomainError) as error:
        service.confirm(batch["id"], {"expectedVersion": 2, "reason": "Duplicate confirmation"})
    assert error.value.status == 409
    assert TransactionService(factory).get(first["id"])["status"] == "SETTLED"
    assert TransactionService(factory).get(euro["id"])["status"] == "CLEARED"
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(JournalEntry).where(JournalEntry.event_type == "SETTLEMENT")
            )
            == 2
        )


def test_refund_settlement_is_credit_and_negative_net_without_cross_currency_arithmetic(factory):
    transaction = captured(factory, 7500)
    settle(factory, transaction)
    transaction_service = TransactionService(factory)
    refund, _ = transaction_service.refund(transaction["id"], uuid4().hex, "Full synthetic refund")
    transaction_service.authorize(refund["id"])
    refund = transaction_service.capture(refund["id"])
    batch = settle(factory, refund)
    assert (batch["grossDebitMinor"], batch["grossCreditMinor"], batch["netSettlementMinor"]) == (
        0,
        7500,
        -7500,
    )
    assert transaction_service.get(transaction["id"])["status"] == "REFUNDED"
    assert transaction_service.get(refund["id"])["status"] == "SETTLED"


def test_database_unique_membership_rejects_second_batch_item(factory):
    transaction = captured(factory)
    clear(factory, transaction)
    first = SettlementService(factory).create({"businessDate": BUSINESS_DATE, "currency": "USD"})
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            second = SettlementBatch(
                business_date=date.fromisoformat(BUSINESS_DATE),
                currency="USD",
                transaction_count=1,
                gross_debit_minor=50000,
                gross_credit_minor=0,
                net_minor=50000,
            )
            session.add(second)
            session.flush()
            session.add(
                SettlementItem(
                    batch_id=second.id,
                    transaction_id=UUID(transaction["id"]),
                    amount_minor=50000,
                    direction="DEBIT",
                )
            )
            session.flush()
    assert SettlementService(factory).items(first["id"])["total"] == 1


def test_settlement_confirmation_is_atomic_when_a_later_ledger_write_fails(factory, monkeypatch):
    transactions = [captured(factory, 7000), captured(factory, 8000)]
    for transaction in transactions:
        clear(factory, transaction)
    service = SettlementService(factory)
    batch = service.create({"businessDate": BUSINESS_DATE, "currency": "USD"})
    batch = service.ready(batch["id"], {"expectedVersion": 0, "reason": "Ready"})
    batch = service.submit(batch["id"], {"expectedVersion": 1, "reason": "Submit"})
    from app import transactions as transaction_module

    original = transaction_module.ledger_settle
    calls = 0

    def fail_second(session, transaction):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DomainError(409, "Synthetic ledger failure")
        return original(session, transaction)

    monkeypatch.setattr(transaction_module, "ledger_settle", fail_second)
    with pytest.raises(DomainError):
        service.confirm(batch["id"], {"expectedVersion": 2, "reason": "Confirm must be atomic"})
    assert service.get(batch["id"])["status"] == "SUBMITTED"
    assert all(
        TransactionService(factory).get(transaction["id"])["status"] == "CLEARED"
        for transaction in transactions
    )
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(JournalEntry).where(JournalEntry.event_type == "SETTLEMENT")
            )
            == 0
        )
    monkeypatch.setattr(transaction_module, "ledger_settle", original)
    assert (
        service.confirm(batch["id"], {"expectedVersion": 2, "reason": "Retry confirmed evidence"})["status"]
        == "CONFIRMED"
    )


@pytest.mark.postgres
def test_postgres_concurrent_clearing_records_have_one_financial_transition(postgres_factory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory = postgres_factory
    transaction = captured(factory)
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=5)
        return ClearingService(factory).create(clearing_body(transaction))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert len({result["id"] for result in results}) == 1
    assert sorted(result["duplicate"] for result in results) == [False, True]
    assert TransactionService(factory).get(transaction["id"])["status"] == "CLEARED"


@pytest.mark.postgres
def test_postgres_concurrent_settlement_selection_and_confirmation_do_not_duplicate_money(postgres_factory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory = postgres_factory
    for amount in (11100, 22200):
        clear(factory, captured(factory, amount))
    barrier = Barrier(2)

    def create_batch():
        barrier.wait(timeout=5)
        try:
            return SettlementService(factory).create(
                {"businessDate": BUSINESS_DATE, "currency": "USD", "maxItems": 1}
            )
        except DomainError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_batch(), range(2)))
    # A statement snapshot may encounter membership committed just before acquiring
    # its row lock. The unique constraint rejects that attempt; retry after rollback.
    batches = []
    for result in results:
        if isinstance(result, dict):
            batches.append(result)
        else:
            assert result == 409
            batches.append(
                SettlementService(factory).create(
                    {"businessDate": BUSINESS_DATE, "currency": "USD", "maxItems": 1}
                )
            )
    first_items = SettlementService(factory).items(batches[0]["id"])["items"]
    second_items = SettlementService(factory).items(batches[1]["id"])["items"]
    assert {item["transactionId"] for item in first_items}.isdisjoint(
        item["transactionId"] for item in second_items
    )
    assert sum(batch["netSettlementMinor"] for batch in batches) == 33300
    service = SettlementService(factory)
    batch = service.ready(batches[0]["id"], {"expectedVersion": 0, "reason": "Ready"})
    batch = service.submit(batch["id"], {"expectedVersion": 1, "reason": "Submitted"})
    barrier = Barrier(2)

    def confirm():
        barrier.wait(timeout=5)
        try:
            return service.confirm(batch["id"], {"expectedVersion": 2, "reason": "Concurrent confirmation"})[
                "status"
            ]
        except DomainError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm(), range(2)))
    assert results.count("CONFIRMED") == 1 and results.count(409) == 1
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(JournalEntry).where(JournalEntry.event_type == "SETTLEMENT")
            )
            == 1
        )


@pytest.mark.postgres
def test_postgres_same_transaction_cannot_enter_two_concurrent_batches(postgres_factory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory = postgres_factory
    transaction = captured(factory)
    clear(factory, transaction)
    barrier = Barrier(2)

    def create_batch():
        barrier.wait(timeout=5)
        try:
            return SettlementService(factory).create({"businessDate": BUSINESS_DATE, "currency": "USD"})
        except DomainError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_batch(), range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count(409) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SettlementItem)) == 1
        assert session.scalar(select(func.count()).select_from(SettlementBatch)) == 1


@pytest.mark.postgres
def test_postgres_same_csv_concurrent_upload_commits_one_import_and_row_effect(postgres_factory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factory = postgres_factory
    transaction = captured(factory)
    content = (
        ",".join(ClearingService.HEADER)
        + "\n"
        + f"{transaction['id']},CSV-CONCURRENT,50000,USD,{BUSINESS_DATE}\n"
    ).encode()
    barrier = Barrier(2)

    def import_file():
        barrier.wait(timeout=5)
        return ClearingService(factory).import_csv(content, "concurrent.csv")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: import_file(), range(2)))
    assert len({result["id"] for result in results}) == 1
    assert sorted(result["duplicateFile"] for result in results) == [False, True]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ClearingImport)) == 1
        assert session.scalar(select(func.count()).select_from(ClearingImportRow)) == 1
        assert session.scalar(select(func.count()).select_from(ClearingRecord)) == 1
