from uuid import UUID

from fastapi import APIRouter, Header, Response

from .schemas import AccountRequest, ActionRequest, CustomerRequest, TransactionRequest
from .transactions import TransactionService

router = APIRouter(prefix="/api", tags=["Transactions & ledger"])


@router.post("/customers", status_code=201)
def create_customer(body: CustomerRequest):
    return TransactionService().create_customer(body.model_dump())


@router.get("/customers")
def customers(page: int = 0, size: int = 20):
    return TransactionService().customers(page, size)


@router.post("/accounts", status_code=201)
def create_account(body: AccountRequest):
    return TransactionService().create_account(body.model_dump())


@router.get("/accounts")
def accounts(page: int = 0, size: int = 20):
    return TransactionService().accounts(page, size)


@router.post("/transactions", status_code=201)
def create_transaction(
    body: TransactionRequest, response: Response, idempotency_key: str | None = Header(default=None)
):
    result, replayed = TransactionService().create(body.model_dump(), idempotency_key)
    response.status_code = 200 if replayed else 201
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    response.headers["Location"] = f"/api/transactions/{result['id']}"
    return result


@router.get("/transactions")
def transactions(page: int = 0, size: int = 20, status: str | None = None):
    return TransactionService().list(page, size, status)


@router.get("/transactions/by-reference/{reference}")
def find_transaction(reference: str):
    return TransactionService().find_external(reference)


@router.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: UUID):
    return TransactionService().get(transaction_id)


@router.get("/transactions/{transaction_id}/history")
def history(transaction_id: UUID, page: int = 0, size: int = 20):
    return TransactionService().history(transaction_id, page, size)


@router.get("/transactions/{transaction_id}/ledger")
def ledger(transaction_id: UUID, page: int = 0, size: int = 20):
    return TransactionService().ledger(transaction_id, page, size)


@router.post("/transactions/{transaction_id}/authorize")
def authorize(transaction_id: UUID):
    return TransactionService().authorize(transaction_id)


@router.post("/transactions/{transaction_id}/capture")
def capture(transaction_id: UUID):
    return TransactionService().capture(transaction_id)


@router.post("/transactions/{transaction_id}/reverse")
def reverse(transaction_id: UUID, body: ActionRequest):
    return TransactionService().reverse(transaction_id, body.reason)


@router.post("/transactions/{transaction_id}/refund", status_code=201)
def refund(
    transaction_id: UUID,
    body: ActionRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None),
):
    result, replayed = TransactionService().refund(transaction_id, idempotency_key, body.reason)
    response.status_code = 200 if replayed else 201
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result
