from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError

from app.errors import DomainError
from app.ledger import Posting, post_journal
from app.models import FinancialTransaction, IdempotencyClaim, JournalEntry, TransactionHistory
from app.transactions import TRANSITIONS, TransactionService


def instruction(factory, amount=50000, currency="USD"):
    service = TransactionService(factory)
    customer = service.create_customer(
        {"externalReference": "DEMO-C-" + uuid4().hex, "displayName": "Synthetic Customer"}
    )
    account = service.create_account(
        {"customerId": customer["id"], "accountReference": "DEMO-A-" + uuid4().hex, "currency": currency}
    )
    return {
        "externalReference": "DEMO-T-" + uuid4().hex,
        "transactionType": "CARD_PURCHASE",
        "amountMinor": amount,
        "currency": currency,
        "sourceAccountId": account["id"],
        "counterpartyReference": "DEMO-MERCHANT",
        "businessDate": "2026-11-08",
    }


def test_idempotency_snapshot_replay_normalization_and_conflict(factory):
    service = TransactionService(factory)
    body = instruction(factory)
    key = uuid4().hex
    tx, replayed = service.create(body, key)
    assert not replayed and tx["status"] == "RECEIVED"
    service.authorize(tx["id"])
    replay, replayed = service.create(
        {**body, "externalReference": "  " + body["externalReference"] + "  "}, key
    )
    assert replayed and replay == tx
    with pytest.raises(DomainError) as error:
        service.create({**body, "amountMinor": body["amountMinor"] + 1}, key)
    assert error.value.status == 409
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(FinancialTransaction)) == 1
        assert s.scalar(select(func.count()).select_from(IdempotencyClaim)) == 1


@pytest.mark.parametrize("amount", [0, -1, 1.5, "100", True, 10**12 + 1])
def test_money_rejects_noninteger_and_out_of_range(factory, amount):
    with pytest.raises(ValidationError):
        TransactionService(factory).create({**instruction(factory), "amountMinor": amount}, uuid4().hex)


def test_cross_currency_account_and_missing_key_rejected(factory):
    service = TransactionService(factory)
    body = instruction(factory)
    with pytest.raises(DomainError) as error:
        service.create(body, None)
    assert error.value.status == 400
    with pytest.raises(DomainError):
        service.create({**body, "currency": "EUR"}, uuid4().hex)
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(FinancialTransaction)) == 0


def test_lifecycle_history_and_reversal_append_compensating_journal(factory):
    service = TransactionService(factory)
    tx, _ = service.create(instruction(factory), uuid4().hex)
    with pytest.raises(DomainError):
        service.capture(tx["id"])
    assert service.authorize(tx["id"])["status"] == "AUTHORIZED"
    service.capture(tx["id"])
    assert service.reverse(tx["id"], "Synthetic request cancelled before clearing")["status"] == "REVERSED"
    history = service.history(tx["id"])["items"]
    assert [h["newStatus"] for h in history] == [
        "RECEIVED",
        "VALIDATED",
        "AUTHORIZED",
        "CAPTURED",
        "REVERSED",
    ]
    assert [h["version"] for h in history] == list(range(5))
    assert all(h["correlationId"] and h["actor"] for h in history)
    ledger = service.ledger(tx["id"])["items"]
    assert len(ledger) == 2 and ledger[0]["debitAccountId"] == ledger[1]["creditAccountId"]
    with pytest.raises(DomainError):
        service.capture(tx["id"])


def test_decline_never_creates_money_and_timeout_rolls_back(factory):
    service = TransactionService(factory)
    tx, _ = service.create(instruction(factory, 13), uuid4().hex)
    assert service.authorize(tx["id"])["status"] == "DECLINED"
    assert service.ledger(tx["id"])["total"] == 0

    class TimeoutNetwork:
        def authorize(self, *args):
            raise DomainError(503, "Synthetic network timeout")

    tx, _ = service.create(instruction(factory), uuid4().hex)
    with pytest.raises(DomainError):
        TransactionService(factory, TimeoutNetwork()).authorize(tx["id"])
    assert service.get(tx["id"])["status"] == "RECEIVED" and service.history(tx["id"])["total"] == 1


def test_unbalanced_journal_rejected_and_committed_ledger_is_immutable(factory):
    service = TransactionService(factory)
    tx, _ = service.create(instruction(factory), uuid4().hex)
    with pytest.raises(DomainError):
        with factory.begin() as s:
            post_journal(
                s,
                UUID(tx["id"]),
                "CAPTURE",
                [
                    Posting("CUSTOMER_RECEIVABLE", "DEBIT", 50000, "USD"),
                    Posting("NETWORK_PAYABLE", "CREDIT", 45000, "USD"),
                ],
            )
    service.authorize(tx["id"])
    service.capture(tx["id"])
    with factory() as s:
        rows = s.execute(
            text("SELECT side,SUM(amount_minor) AS amount FROM ledger_posting GROUP BY side")
        ).all()
        assert dict(rows) == {"CREDIT": 50000, "DEBIT": 50000}
    with pytest.raises(DatabaseError):
        with factory.begin() as s:
            s.execute(text("UPDATE journal_entry SET amount_minor=1"))
    with pytest.raises(DatabaseError):
        with factory.begin() as s:
            s.execute(text("DELETE FROM journal_entry"))


def test_no_arbitrary_terminal_transitions():
    for status in ("DECLINED", "REVERSED", "REFUNDED"):
        assert TRANSITIONS[status] == set()
    assert "REVERSED" not in TRANSITIONS["SETTLED"]


def test_api_contract_problem_details_and_pagination(client):
    customer = client.post(
        "/api/customers", json={"externalReference": "DEMO-C-API", "displayName": "Synthetic API"}
    )
    assert customer.status_code == 201, customer.text
    account = client.post(
        "/api/accounts",
        json={"customerId": customer.json()["id"], "accountReference": "DEMO-A-API", "currency": "USD"},
    ).json()
    body = {
        "externalReference": "DEMO-API-TX",
        "transactionType": "CARD_PURCHASE",
        "amountMinor": 50000,
        "currency": "USD",
        "sourceAccountId": account["id"],
        "counterpartyReference": "DEMO-MERCHANT",
        "businessDate": "2026-11-08",
    }
    missing = client.post("/api/transactions", json=body)
    assert missing.status_code == 400 and missing.json()["requestId"]
    created = client.post(
        "/api/transactions",
        json=body,
        headers={"Idempotency-Key": "api-one", "X-Request-ID": "interview-demo"},
    )
    assert created.status_code == 201, created.text
    assert created.headers["X-Request-ID"] == "interview-demo"
    assert (
        client.post("/api/transactions", json=body, headers={"Idempotency-Key": "api-one"}).status_code == 200
    )
    assert client.get("/api/transactions?size=101").status_code == 400
    assert (
        client.post(
            "/api/transactions", json={**body, "amountMinor": 500.0}, headers={"Idempotency-Key": "bad"}
        ).status_code
        == 422
    )
    assert client.get("/api/transactions/not-a-uuid").status_code == 422
    metrics = client.get("/metrics")
    assert metrics.status_code == 200 and b"banking_http_request_seconds" in metrics.content


def test_reader_permission_boundary_and_error_privacy(client, monkeypatch):
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_API_USERNAME", "synthetic-operator")
    monkeypatch.setenv("APP_API_PASSWORD", "synthetic-operator-secret")
    monkeypatch.setenv("APP_READONLY_USERNAME", "synthetic-reader")
    monkeypatch.setenv("APP_READONLY_PASSWORD", "synthetic-reader-secret")
    assert client.get("/health").status_code == 200
    denied = client.get("/api/transactions")
    assert denied.status_code == 401 and denied.json()["requestId"]
    reader = ("synthetic-reader", "synthetic-reader-secret")
    assert client.get("/api/transactions", auth=reader).status_code == 200
    assert client.post("/api/transactions", json={}, auth=reader).status_code == 403
    assert client.patch("/api/exceptions/" + str(uuid4()), json={}, auth=reader).status_code == 403
    assert client.get("/metrics", auth=reader).status_code == 403
    response = client.post(
        "/api/customers", json={}, auth=("synthetic-operator", "synthetic-operator-secret")
    )
    assert response.status_code == 422 and "synthetic-operator-secret" not in response.text


@pytest.mark.postgres
def test_postgres_concurrent_claim_prevents_duplicate_transactions(postgres_factory):
    service = TransactionService(postgres_factory)
    body = instruction(postgres_factory)
    barrier = Barrier(6)
    key = uuid4().hex

    def submit():
        barrier.wait(timeout=10)
        return service.create(body, key)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: submit(), range(6)))
    assert len({tx["id"] for tx, _ in results}) == 1 and sum(not replay for _, replay in results) == 1
    with postgres_factory() as s:
        assert s.scalar(select(func.count()).select_from(FinancialTransaction)) == 1
        assert s.scalar(select(func.count()).select_from(TransactionHistory)) == 1


@pytest.mark.postgres
def test_postgres_concurrent_capture_posts_one_journal(postgres_factory):
    service = TransactionService(postgres_factory)
    tx, _ = service.create(instruction(postgres_factory), uuid4().hex)
    service.authorize(tx["id"])
    barrier = Barrier(2)

    def capture():
        barrier.wait(timeout=10)
        try:
            return service.capture(tx["id"])["status"]
        except DomainError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(lambda _: capture(), range(2))) == {"CAPTURED", 409}
    with postgres_factory() as s:
        assert s.scalar(select(func.count()).select_from(JournalEntry)) == 1


def test_balanced_wrong_currency_and_amount_journal_rejected(factory):
    service = TransactionService(factory)
    tx, _ = service.create(instruction(factory), uuid4().hex)
    for amount, currency in ((50000, "EUR"), (123, "USD")):
        with pytest.raises(DomainError) as error:
            with factory.begin() as session:
                post_journal(
                    session,
                    UUID(tx["id"]),
                    "CAPTURE",
                    [
                        Posting("CUSTOMER_RECEIVABLE", "DEBIT", amount, currency),
                        Posting("NETWORK_PAYABLE", "CREDIT", amount, currency),
                    ],
                )
        assert error.value.status == 422
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_refund_reason_is_fingerprinted_and_audited(factory):
    from test_clearing_settlement import captured, settle

    original = captured(factory)
    settle(factory, original)
    service = TransactionService(factory)
    key = uuid4().hex
    refund, _ = service.refund(original["id"], key, "Synthetic customer refund request")
    assert service.history(refund["id"])["items"][0]["reason"] == "Synthetic customer refund request"
    assert service.refund(original["id"], key, "Synthetic customer refund request")[1]
    with pytest.raises(DomainError) as error:
        service.refund(original["id"], key, "A different refund reason")
    assert error.value.status == 409


def test_unknown_route_and_oversized_chunked_body_use_problem_details(client):
    response = client.get("/api/unknown")
    assert response.status_code == 404 and response.json()["requestId"]
    response = client.post("/api/transactions", content=iter([b"a" * 1048576, b"b" * 1048577]))
    assert response.status_code == 413 and response.json()["requestId"]


def test_utf8_basic_credentials_authenticate_or_reject_without_server_error(client, monkeypatch):
    import base64

    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_API_USERNAME", "synthetic-opérateur")
    monkeypatch.setenv("APP_API_PASSWORD", "synthetic-sécret")

    def header(value):
        return {"Authorization": "Basic " + base64.b64encode(value.encode("utf-8")).decode("ascii")}

    accepted = client.get("/api/transactions", headers=header("synthetic-opérateur:synthetic-sécret"))
    denied = client.get("/api/transactions", headers=header("synthetic-é:wrong"))
    assert accepted.status_code == 200
    assert denied.status_code == 401 and denied.json()["requestId"]
