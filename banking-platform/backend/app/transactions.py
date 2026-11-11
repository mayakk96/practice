import hashlib
import json
import re
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from . import db
from .common import actor, as_dict, correlation_id, now, page_result, validate_page
from .errors import DomainError
from .ledger import paired_post
from .models import (
    BankAccount,
    Customer,
    FinancialTransaction,
    IdempotencyClaim,
    JournalEntry,
    TransactionHistory,
)
from .network import PaymentNetworkClient
from .schemas import AccountRequest, CustomerRequest, TransactionRequest

TRANSITIONS = {
    "RECEIVED": {"VALIDATED"},
    "VALIDATED": {"AUTHORIZED", "DECLINED"},
    "AUTHORIZED": {"CAPTURED", "REVERSED"},
    "CAPTURED": {"CLEARED", "REVERSED"},
    "CLEARED": {"SETTLED"},
    "SETTLED": {"REFUNDED"},
    "DECLINED": set(),
    "REVERSED": set(),
    "REFUNDED": set(),
}


def get_transaction_locked(session, transaction_id):
    tx = session.scalar(
        select(FinancialTransaction)
        .where(FinancialTransaction.id == UUID(str(transaction_id)))
        .with_for_update()
    )
    if tx is None:
        raise DomainError(404, "Transaction not found.")
    return tx


def event_payload(tx):
    return {
        "status": tx.status,
        "transactionType": tx.transaction_type,
        "amountMinor": tx.amount_minor,
        "currency": tx.currency,
        "businessDate": tx.business_date.isoformat(),
        "version": tx.version,
    }


def record_history(session, tx, previous, reason):
    session.add(
        TransactionHistory(
            transaction_id=tx.id,
            previous_status=previous,
            new_status=tx.status,
            reason=reason,
            actor=actor(),
            correlation_id=correlation_id(),
            version=tx.version,
        )
    )
    from .events import record_event

    record_event(session, "Transaction" + tx.status.title(), tx.id, event_payload(tx))


def transition(session, tx, target, reason):
    if target not in TRANSITIONS.get(tx.status, set()):
        raise DomainError(409, f"Transition from {tx.status} to {target} is not allowed.")
    old = tx.status
    version = tx.version
    changed = session.execute(
        update(FinancialTransaction)
        .where(
            FinancialTransaction.id == tx.id,
            FinancialTransaction.version == version,
            FinancialTransaction.status == old,
        )
        .values(status=target, version=version + 1, updated_at=now()),
        execution_options={"synchronize_session": False},
    )
    if changed.rowcount != 1:
        raise DomainError(409, "Transaction was concurrently changed; reload before retrying.")
    session.refresh(tx)
    record_history(session, tx, old, reason)
    session.flush()
    return tx


def ledger_settle(session, tx):
    debit, credit = (
        ("CASH_CLEARING", "NETWORK_PAYABLE")
        if tx.transaction_type == "REFUND"
        else ("NETWORK_PAYABLE", "CASH_CLEARING")
    )
    return paired_post(session, tx, "SETTLEMENT", debit, credit)


class TransactionService:
    def __init__(self, factory=None, network=None):
        self.factory = factory or db.SessionLocal
        self.network = network or PaymentNetworkClient()

    def _get(self, session, transaction_id):
        tx = session.get(FinancialTransaction, UUID(str(transaction_id)))
        if tx is None:
            raise DomainError(404, "Transaction not found.")
        return tx

    def create_customer(self, body):
        req = CustomerRequest.model_validate(body)
        with self.factory.begin() as s:
            customer = Customer(**req.model_dump())
            s.add(customer)
            s.flush()
            return as_dict(customer)

    def create_account(self, body):
        req = AccountRequest.model_validate(body)
        with self.factory.begin() as s:
            customer = s.get(Customer, req.customer_id)
            if customer is None:
                raise DomainError(404, "Synthetic customer not found.")
            if customer.status != "ACTIVE":
                raise DomainError(409, "Customer is not active.")
            account = BankAccount(**req.model_dump())
            s.add(account)
            s.flush()
            return as_dict(account)

    def accounts(self, page=0, size=20):
        return self._list_model(BankAccount, page, size)

    def customers(self, page=0, size=20):
        return self._list_model(Customer, page, size)

    def _list_model(self, model, page, size):
        validate_page(page, size)
        with self.factory() as s:
            total = s.scalar(select(func.count()).select_from(model))
            rows = s.scalars(
                select(model).order_by(model.created_at, model.id).offset(page * size).limit(size)
            ).all()
            return page_result([as_dict(x) for x in rows], page, size, total)

    def _fingerprint(self, body):
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

    def _key(self, key):
        if not key or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", key):
            raise DomainError(400, "Idempotency-Key containing 1..100 safe reference characters is required.")

    def _replay(self, claim, fingerprint):
        if claim.fingerprint != fingerprint:
            raise DomainError(409, "Idempotency-Key was already used with a different request.")
        if not claim.response_json:
            raise DomainError(409, "Original request is incomplete; investigate before retrying.")
        return json.loads(claim.response_json), True

    def create(self, body, key):
        req = TransactionRequest.model_validate(body)
        return self._create(req.model_dump(), key)

    def _create(self, body, key, creation_reason=None):
        self._key(key)
        fingerprint = self._fingerprint({"instruction": body, "reason": creation_reason})
        try:
            with self.factory.begin() as s:
                claim = s.get(IdempotencyClaim, key)
                if claim:
                    return self._replay(claim, fingerprint)
                claim = IdempotencyClaim(request_key=key, fingerprint=fingerprint)
                s.add(claim)
                s.flush()  # unique claim serializes requests across all application processes
                account = s.get(BankAccount, body["source_account_id"])
                if not account:
                    raise DomainError(404, "Synthetic account not found.")
                if account.status != "ACTIVE" or account.currency != body["currency"]:
                    raise DomainError(409, "Account must be active and use the transaction currency.")
                original_id = body.get("original_transaction_id")
                if original_id:
                    original = get_transaction_locked(s, original_id)
                    if original.status != "SETTLED" or original.transaction_type == "REFUND":
                        raise DomainError(409, "Only a settled original payment can be refunded once.")
                tx = FinancialTransaction(
                    id=uuid4(), **body, status="RECEIVED", version=0, created_at=now(), updated_at=now()
                )
                s.add(tx)
                s.flush()
                record_history(s, tx, None, creation_reason or "Synthetic instruction received")
                response = as_dict(tx)
                claim.transaction_id = tx.id
                claim.response_json = json.dumps(response, sort_keys=True)
                return response, False
        except IntegrityError:
            # PostgreSQL aborts the loser transaction. Read the winner only after rollback in a fresh one.
            with self.factory() as s:
                claim = s.get(IdempotencyClaim, key)
                if claim:
                    return self._replay(claim, fingerprint)
            raise DomainError(409, "External reference or refund already exists.") from None

    def get(self, transaction_id):
        with self.factory() as s:
            return as_dict(self._get(s, transaction_id))

    def find_external(self, reference):
        if not reference or len(reference) > 100:
            raise DomainError(400, "External reference must contain 1..100 characters.")
        with self.factory() as s:
            tx = s.scalar(
                select(FinancialTransaction).where(FinancialTransaction.external_reference == reference)
            )
            if not tx:
                raise DomainError(404, "Transaction not found.")
            return as_dict(tx)

    def list(self, page=0, size=20, status=None):
        validate_page(page, size)
        if status and status not in TRANSITIONS:
            raise DomainError(400, "Unknown transaction status.")
        with self.factory() as s:
            query = select(FinancialTransaction)
            if status:
                query = query.where(FinancialTransaction.status == status)
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            rows = s.scalars(
                query.order_by(FinancialTransaction.created_at, FinancialTransaction.id)
                .offset(page * size)
                .limit(size)
            ).all()
            return page_result([as_dict(x) for x in rows], page, size, total)

    def list_failed(self, page=0, size=20):
        return self.list(page, size, "DECLINED")

    def history(self, transaction_id, page=0, size=20):
        validate_page(page, size)
        with self.factory() as s:
            tx = self._get(s, transaction_id)
            query = select(TransactionHistory).where(TransactionHistory.transaction_id == tx.id)
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            rows = s.scalars(query.order_by(TransactionHistory.version).offset(page * size).limit(size)).all()
            return page_result([as_dict(x) for x in rows], page, size, total)

    def authorize(self, transaction_id):
        # The network call is bounded but holds this row lock. A long real workflow needs durable orchestration.
        with self.factory.begin() as s:
            tx = get_transaction_locked(s, transaction_id)
            if tx.status == "RECEIVED":
                transition(s, tx, "VALIDATED", "Account and monetary validation passed")
            if tx.status != "VALIDATED":
                raise DomainError(409, "Only a received or validated instruction can be authorized.")
            account = s.get(BankAccount, tx.source_account_id)
            if not account or account.status != "ACTIVE" or account.currency != tx.currency:
                raise DomainError(409, "Account validation failed.")
            decision = self.network.authorize(str(tx.id), tx.amount_minor, tx.currency, correlation_id())
            tx.network_reference = decision.network_reference
            s.flush()
            transition(s, tx, "AUTHORIZED" if decision.approved else "DECLINED", "Fictional network decision")
            return as_dict(tx)

    def capture(self, transaction_id):
        with self.factory.begin() as s:
            tx = get_transaction_locked(s, transaction_id)
            if tx.status != "AUTHORIZED":
                raise DomainError(409, "Only an authorized transaction can be captured.")
            if tx.transaction_type == "REFUND":
                original = get_transaction_locked(s, tx.original_transaction_id)
                transition(s, original, "REFUNDED", "Full refund captured in linked transaction")
                paired_post(s, tx, "CAPTURE", "NETWORK_PAYABLE", "CUSTOMER_RECEIVABLE")
            else:
                paired_post(s, tx, "CAPTURE", "CUSTOMER_RECEIVABLE", "NETWORK_PAYABLE")
            transition(s, tx, "CAPTURED", "Capture journal booked")
            return as_dict(tx)

    def reverse(self, transaction_id, reason):
        if not reason or not reason.strip() or len(reason) > 500:
            raise DomainError(400, "A reason of 1..500 characters is required.")
        with self.factory.begin() as s:
            tx = get_transaction_locked(s, transaction_id)
            if tx.transaction_type == "REFUND":
                raise DomainError(409, "Refund reversal is outside this educational workflow.")
            if tx.status not in ("AUTHORIZED", "CAPTURED"):
                raise DomainError(409, "Only an authorized or captured instruction can be reversed.")
            if tx.status == "CAPTURED":
                paired_post(s, tx, "REVERSAL", "NETWORK_PAYABLE", "CUSTOMER_RECEIVABLE")
            transition(s, tx, "REVERSED", reason.strip())
            return as_dict(tx)

    def refund(self, transaction_id, key, reason):
        original = self.get(transaction_id)
        if not reason or not reason.strip() or len(reason) > 500:
            raise DomainError(400, "A refund reason is required.")
        body = {
            "external_reference": f"REFUND-{transaction_id}",
            "transaction_type": "REFUND",
            "amount_minor": original["amountMinor"],
            "currency": original["currency"],
            "source_account_id": UUID(original["sourceAccountId"]),
            "counterparty_reference": original["counterpartyReference"],
            "original_transaction_id": UUID(str(transaction_id)),
            "business_date": __import__("datetime").date.fromisoformat(original["businessDate"]),
        }
        # Include reason in the idempotency scope while keeping the stored aggregate fields explicit.
        return self._create(body, key, creation_reason=reason.strip())

    def ledger(self, transaction_id, page=0, size=20):
        validate_page(page, size)
        with self.factory() as s:
            tx = self._get(s, transaction_id)
            query = select(JournalEntry).where(JournalEntry.transaction_id == tx.id)
            total = s.scalar(select(func.count()).select_from(query.subquery()))
            rows = s.scalars(
                query.order_by(JournalEntry.created_at, JournalEntry.id).offset(page * size).limit(size)
            ).all()
            return page_result([as_dict(x) for x in rows], page, size, total)
