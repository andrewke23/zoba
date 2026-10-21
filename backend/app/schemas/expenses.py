from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer, model_validator

# Money serializes as a canonical two-decimal string (e.g. "10.00") so JSON
# responses never drop trailing zeros the way Decimal("10") would.
Money = Annotated[
    Decimal,
    PlainSerializer(lambda value: f"{value:.2f}", return_type=str, when_used="json"),
]


class ExpenseSplitCreate(BaseModel):
    debtor_id: UUID
    amount_owed: Decimal = Field(gt=0, le=Decimal("21474836.47"), max_digits=10, decimal_places=2)


class ExpenseCreate(BaseModel):
    payer_id: UUID
    description: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(
        gt=0,
        le=Decimal("21474836.47"),
        max_digits=10,
        decimal_places=2,
    )
    date: datetime
    splits: list[ExpenseSplitCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_splits(self) -> "ExpenseCreate":
        debtor_ids = [split.debtor_id for split in self.splits]
        if len(debtor_ids) != len(set(debtor_ids)):
            raise ValueError("A debtor may only appear once")
        if self.payer_id in debtor_ids:
            raise ValueError("The payer's share is calculated from the remaining amount")
        if sum((split.amount_owed for split in self.splits), Decimal(0)) > self.amount:
            raise ValueError("Debtor shares cannot exceed the expense amount")
        if self.date.utcoffset() is None:
            raise ValueError("date must include a timezone")
        return self


class ExpenseSplitRead(BaseModel):
    debtor_id: UUID
    amount_owed: Money


class ExpenseRead(BaseModel):
    id: UUID
    trip_id: UUID
    payer_id: UUID
    description: str
    amount: Money
    date: datetime
    splits: list[ExpenseSplitRead]


class TransferRead(BaseModel):
    from_user: UUID
    to_user: UUID
    amount: Money


class BalanceRead(BaseModel):
    """One member's net position, in cents to match the data layer."""

    user_id: UUID
    paid_cents: int
    owed_cents: int
    net_cents: int


class SettlementRead(BaseModel):
    balances: list[BalanceRead]
    transfers: list[TransferRead]


class CostEstimateRead(BaseModel):
    trip_id: UUID
    currency: str
    per_person_total: Money
    itinerary_stop_count: int
    priced_stop_count: int
    unpriced_stop_count: int
    is_complete: bool
