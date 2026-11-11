from dataclasses import dataclass

from .errors import DomainError
from .models import FinancialTransaction, JournalEntry, LedgerAccount


@dataclass(frozen=True)
class Posting:
    account_code: str
    side: str
    amount_minor: int
    currency: str


def post_journal(session, transaction_id, event_type, postings):
    """Two-sided journal storage makes an unbalanced committed entry unrepresentable."""
    if event_type not in {"CAPTURE", "REVERSAL", "SETTLEMENT"}:
        raise DomainError(422, "Unsupported financial event.")
    if len(postings) != 2 or {p.side for p in postings} != {"DEBIT", "CREDIT"}:
        raise DomainError(422, "A journal requires one debit and one credit.")
    debit = next(p for p in postings if p.side == "DEBIT")
    credit = next(p for p in postings if p.side == "CREDIT")
    if (
        type(debit.amount_minor) is not int
        or type(credit.amount_minor) is not int
        or debit.amount_minor <= 0
        or debit.amount_minor > 10**12
        or debit.amount_minor != credit.amount_minor
        or debit.currency != credit.currency
    ):
        raise DomainError(422, "Journal debit and credit amounts and currencies must balance exactly.")
    debit_id, credit_id = f"{debit.account_code}:{debit.currency}", f"{credit.account_code}:{credit.currency}"
    if (
        debit_id == credit_id
        or not session.get(LedgerAccount, debit_id)
        or not session.get(LedgerAccount, credit_id)
    ):
        raise DomainError(422, "Distinct known ledger accounts in one currency are required.")
    transaction = session.get(FinancialTransaction, transaction_id)
    if transaction is None or (transaction.amount_minor, transaction.currency) != (
        debit.amount_minor,
        debit.currency,
    ):
        raise DomainError(422, "Full-value journal amount and currency must match the transaction.")
    entry = JournalEntry(
        transaction_id=transaction_id,
        event_type=event_type,
        debit_account_id=debit_id,
        credit_account_id=credit_id,
        amount_minor=debit.amount_minor,
        currency=debit.currency,
    )
    session.add(entry)
    session.flush()
    return entry


def paired_post(session, tx, event_type, debit, credit):
    return post_journal(
        session,
        tx.id,
        event_type,
        [
            Posting(debit, "DEBIT", tx.amount_minor, tx.currency),
            Posting(credit, "CREDIT", tx.amount_minor, tx.currency),
        ],
    )
