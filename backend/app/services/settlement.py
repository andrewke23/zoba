from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping
from uuid import UUID


@dataclass(frozen=True)
class Transfer:
    from_user: UUID
    to_user: UUID
    amount: Decimal


def minimize_transfers(net_balances: Mapping[UUID, Decimal]) -> list[Transfer]:
    """Return a deterministic greedy settlement for net balances (positive means owed)."""
    balance = {user_id: Decimal(value) for user_id, value in net_balances.items()}
    if sum(balance.values(), Decimal(0)) != 0:
        raise ValueError("Net balances must sum to zero")

    transfers: list[Transfer] = []
    while True:
        debtors = [(user_id, amount) for user_id, amount in balance.items() if amount < 0]
        creditors = [(user_id, amount) for user_id, amount in balance.items() if amount > 0]
        if not debtors and not creditors:
            return transfers
        if not debtors or not creditors:
            raise ValueError("Net balances must sum to zero")

        debtor_id, debtor_balance = min(debtors, key=lambda item: (item[1], str(item[0])))
        creditor_id, creditor_balance = min(creditors, key=lambda item: (-item[1], str(item[0])))
        amount = min(-debtor_balance, creditor_balance)
        transfers.append(Transfer(from_user=debtor_id, to_user=creditor_id, amount=amount))
        balance[debtor_id] += amount
        balance[creditor_id] -= amount
