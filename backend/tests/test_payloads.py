from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.expenses import ExpenseCreate, ExpenseRead, ExpenseSplitRead, TransferRead
from app.schemas.trips import TripSummaryRead


def test_expense_payload_accepts_cent_precision_and_debtor_splits() -> None:
    payer_id = UUID("00000000-0000-0000-0000-000000000001")
    debtor_id = UUID("00000000-0000-0000-0000-000000000002")

    payload = ExpenseCreate.model_validate(
        {
            "payer_id": str(payer_id),
            "description": "Shared dinner",
            "amount": "20.50",
            "date": datetime(2026, 10, 15, tzinfo=timezone.utc),
            "splits": [{"debtor_id": str(debtor_id), "amount_owed": "8.25"}],
        }
    )

    assert payload.amount == Decimal("20.50")
    assert payload.splits[0].amount_owed == Decimal("8.25")


def test_expense_payload_rejects_splits_larger_than_total() -> None:
    with pytest.raises(ValidationError, match="Debtor shares cannot exceed"):
        ExpenseCreate.model_validate(
            {
                "payer_id": "00000000-0000-0000-0000-000000000001",
                "description": "Shared dinner",
                "amount": "20.00",
                "date": datetime(2026, 10, 15, tzinfo=timezone.utc),
                "splits": [
                    {
                        "debtor_id": "00000000-0000-0000-0000-000000000002",
                        "amount_owed": "20.01",
                    }
                ],
            }
        )


def test_expense_payload_requires_timezone_aware_date() -> None:
    with pytest.raises(ValidationError, match="date must include a timezone"):
        ExpenseCreate.model_validate(
            {
                "payer_id": "00000000-0000-0000-0000-000000000001",
                "description": "Shared dinner",
                "amount": "20.00",
                "date": datetime(2026, 10, 15),
                "splits": [
                    {
                        "debtor_id": "00000000-0000-0000-0000-000000000002",
                        "amount_owed": "5.00",
                    }
                ],
            }
        )


def test_money_responses_serialize_with_two_decimal_places() -> None:
    payer_id = UUID("00000000-0000-0000-0000-000000000001")
    debtor_id = UUID("00000000-0000-0000-0000-000000000002")

    expense = ExpenseRead(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        trip_id=UUID("00000000-0000-0000-0000-000000000004"),
        payer_id=payer_id,
        description="Shared dinner",
        amount=Decimal("20"),
        date=datetime(2026, 10, 15, tzinfo=timezone.utc),
        splits=[ExpenseSplitRead(debtor_id=debtor_id, amount_owed=Decimal("10.5"))],
    )
    payload = expense.model_dump(mode="json")

    assert payload["amount"] == "20.00"
    assert payload["splits"][0]["amount_owed"] == "10.50"

    transfer = TransferRead(from_user=debtor_id, to_user=payer_id, amount=Decimal("7"))
    assert transfer.model_dump(mode="json")["amount"] == "7.00"


def test_trip_summary_response_includes_frontend_list_fields() -> None:
    trip_id = UUID("00000000-0000-0000-0000-000000000010")
    organizer_id = UUID("00000000-0000-0000-0000-000000000011")
    summary = TripSummaryRead(
        id=trip_id,
        organizer_id=organizer_id,
        city_id="chicago",
        name="Chicago weekend",
        start_date="2026-11-01",
        end_date="2026-11-03",
        daily_start_time="09:00",
        daily_end_time="18:00",
        home_base_lat=41.88,
        home_base_lon=-87.63,
        home_base_label="Downtown",
        invite_token="invite-token",
        created_at="2026-10-20T12:00:00Z",
        city_name="Chicago",
        my_role="organizer",
        member_count=2,
    )

    payload = summary.model_dump(mode="json")
    assert payload["id"] == str(trip_id)
    assert payload["my_role"] == "organizer"
    assert payload["member_count"] == 2
    assert payload["city_name"] == "Chicago"
