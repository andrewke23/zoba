from decimal import Decimal
from uuid import UUID

import pytest

from app.services.settlement import minimize_transfers


def test_settles_chain_with_one_direct_payment() -> None:
    debtor = UUID("00000000-0000-0000-0000-000000000001")
    intermediary = UUID("00000000-0000-0000-0000-000000000002")
    creditor = UUID("00000000-0000-0000-0000-000000000003")

    transfers = minimize_transfers(
        {
            debtor: Decimal("-10.00"),
            intermediary: Decimal(0),
            creditor: Decimal("10.00"),
        }
    )

    assert len(transfers) == 1
    assert (transfers[0].from_user, transfers[0].to_user, transfers[0].amount) == (
        debtor,
        creditor,
        Decimal("10.00"),
    )


def test_settles_multiple_debtors_and_preserves_cents() -> None:
    users = [UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(1, 5)]

    transfers = minimize_transfers(
        {
            users[0]: Decimal("-6.25"),
            users[1]: Decimal("-3.75"),
            users[2]: Decimal("4.50"),
            users[3]: Decimal("5.50"),
        }
    )

    assert sum((transfer.amount for transfer in transfers), Decimal(0)) == Decimal("10.00")
    assert len(transfers) <= 3
    assert all(transfer.amount > 0 for transfer in transfers)


def test_rejects_unbalanced_net_balances() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000001")

    with pytest.raises(ValueError, match="sum to zero"):
        minimize_transfers({user_id: Decimal("1.00")})
