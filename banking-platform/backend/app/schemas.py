from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .common import camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=camel, populate_by_name=True, extra="forbid", str_strip_whitespace=True
    )


class CustomerRequest(ApiModel):
    external_reference: str = Field(min_length=1, max_length=100, pattern=r"^DEMO-[A-Za-z0-9._:-]+$")
    display_name: str = Field(min_length=1, max_length=80)


class AccountRequest(ApiModel):
    customer_id: UUID
    account_reference: str = Field(min_length=6, max_length=100, pattern=r"^DEMO-[A-Za-z0-9._:-]+$")
    currency: Literal["USD", "EUR", "GBP"]


class TransactionRequest(ApiModel):
    external_reference: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    transaction_type: Literal["CARD_PURCHASE", "ACCOUNT_TRANSFER"]
    amount_minor: StrictInt = Field(gt=0, le=10**12)
    currency: Literal["USD", "EUR", "GBP"]
    source_account_id: UUID
    counterparty_reference: str = Field(min_length=1, max_length=100, pattern=r"^DEMO-[A-Za-z0-9._:-]+$")
    business_date: date


class ActionRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=500)
