from decimal import Decimal
from uuid import UUID

import pytest

from app.main import app
from app.schemas.expenses import BalanceRead, SettlementRead, TransferRead

ALICE = UUID("00000000-0000-0000-0000-000000000001")
BOB = UUID("00000000-0000-0000-0000-000000000002")


def test_settlement_matches_the_frontend_wire_shape() -> None:
    """frontend/src/api/http.ts WireSettlement: {balances: [...], transfers: [...]}."""
    settlement = SettlementRead(
        balances=[
            BalanceRead(user_id=ALICE, paid_cents=3000, owed_cents=1000, net_cents=2000),
            BalanceRead(user_id=BOB, paid_cents=0, owed_cents=2000, net_cents=-2000),
        ],
        transfers=[TransferRead(from_user=BOB, to_user=ALICE, amount=Decimal("20"))],
    )

    body = settlement.model_dump(mode="json")

    assert set(body) == {"balances", "transfers"}
    assert set(body["balances"][0]) == {"user_id", "paid_cents", "owed_cents", "net_cents"}
    assert body["transfers"][0] == {"from_user": str(BOB), "to_user": str(ALICE), "amount": "20.00"}


def test_empty_trip_settles_to_empty_lists() -> None:
    assert SettlementRead(balances=[], transfers=[]).model_dump(mode="json") == {"balances": [], "transfers": []}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/trips/{trip_id}/cost-estimate"),
        ("GET", "/api/v1/trips/{trip_id}/expenses"),
        ("POST", "/api/v1/trips/{trip_id}/expenses"),
        ("DELETE", "/api/v1/trips/{trip_id}/expenses/{expense_id}"),
        ("GET", "/api/v1/trips/{trip_id}/settlement"),
    ],
)
def test_budget_page_routes_are_registered(method: str, path: str) -> None:
    assert method.lower() in app.openapi()["paths"].get(path, {})


def test_settlement_route_returns_the_object_shape() -> None:
    operation = app.openapi()["paths"]["/api/v1/trips/{trip_id}/settlement"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert schema == {"$ref": "#/components/schemas/SettlementRead"}
