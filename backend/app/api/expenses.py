from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member
from app.core.database import get_session
from app.models.entities import Expense, ExpenseShare, Membership, MembershipStatus, Trip
from app.schemas.expenses import (
    BalanceRead,
    ExpenseCreate,
    ExpenseRead,
    ExpenseSplitRead,
    SettlementRead,
    TransferRead,
)
from app.services.settlement import minimize_transfers

router = APIRouter(prefix="/trips/{trip_id}")


@router.post("/expenses", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
async def create_expense(
    payload: ExpenseCreate,
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> ExpenseRead:
    trip, membership = trip_and_membership
    if payload.payer_id != membership.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the authenticated payer can record the expense",
        )
    membership_ids = set(
        (await session.scalars(
            select(Membership.user_id).where(
                Membership.trip_id == trip.id,
                Membership.status == MembershipStatus.JOINED,
            )
        )).all()
    )
    if payload.payer_id not in membership_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Payer must be a trip member")
    if any(split.debtor_id not in membership_ids for split in payload.splits):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="All debtors must be trip members")

    amount_cents = int(payload.amount * 100)
    expense = Expense(
        trip_id=trip.id,
        payer_id=payload.payer_id,
        description=payload.description,
        amount_cents=amount_cents,
        created_at=payload.date,
    )
    session.add(expense)
    await session.flush()

    shares = [
        ExpenseShare(
            expense_id=expense.id,
            user_id=split.debtor_id,
            share_cents=int(split.amount_owed * 100),
        )
        for split in payload.splits
    ]
    remainder = amount_cents - sum(share.share_cents for share in shares)
    if remainder:
        shares.append(ExpenseShare(expense_id=expense.id, user_id=payload.payer_id, share_cents=remainder))
    session.add_all(shares)
    await session.commit()
    return ExpenseRead(
        id=expense.id,
        trip_id=expense.trip_id,
        payer_id=expense.payer_id,
        description=expense.description,
        amount=payload.amount,
        date=expense.created_at,
        splits=[
            ExpenseSplitRead(debtor_id=share.user_id, amount_owed=Decimal(share.share_cents) / 100)
            for share in shares
        ],
    )


@router.get("/expenses", response_model=list[ExpenseRead])
async def list_expenses(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[ExpenseRead]:
    trip, _ = trip_and_membership
    expenses = (
        await session.scalars(
            select(Expense).where(Expense.trip_id == trip.id).order_by(Expense.created_at, Expense.id)
        )
    ).all()
    if not expenses:
        return []
    shares = (
        await session.scalars(
            select(ExpenseShare)
            .where(ExpenseShare.expense_id.in_([expense.id for expense in expenses]))
            .order_by(ExpenseShare.user_id)
        )
    ).all()
    shares_by_expense: dict[UUID, list[ExpenseSplitRead]] = defaultdict(list)
    for share in shares:
        shares_by_expense[share.expense_id].append(
            ExpenseSplitRead(debtor_id=share.user_id, amount_owed=Decimal(share.share_cents) / 100)
        )
    return [
        ExpenseRead(
            id=expense.id,
            trip_id=expense.trip_id,
            payer_id=expense.payer_id,
            description=expense.description or "",
            amount=Decimal(expense.amount_cents) / 100,
            date=expense.created_at,
            splits=shares_by_expense[expense.id],
        )
        for expense in expenses
    ]


@router.get("/settlement", response_model=SettlementRead)
async def read_settlement(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> SettlementRead:
    trip, _ = trip_and_membership
    member_ids = (
        await session.scalars(select(Membership.user_id).where(Membership.trip_id == trip.id))
    ).all()
    paid_cents: dict = {user_id: 0 for user_id in member_ids}
    owed_cents: dict = {user_id: 0 for user_id in member_ids}

    payments = await session.execute(
        select(Expense.payer_id, func.sum(Expense.amount_cents))
        .where(Expense.trip_id == trip.id)
        .group_by(Expense.payer_id)
    )
    for user_id, paid in payments:
        paid_cents[user_id] = paid_cents.get(user_id, 0) + paid

    owed = await session.execute(
        select(ExpenseShare.user_id, func.sum(ExpenseShare.share_cents))
        .join(Expense, Expense.id == ExpenseShare.expense_id)
        .where(Expense.trip_id == trip.id)
        .group_by(ExpenseShare.user_id)
    )
    for user_id, share in owed:
        owed_cents[user_id] = owed_cents.get(user_id, 0) + share

    balances = {
        user_id: Decimal(paid_cents.get(user_id, 0) - owed_cents.get(user_id, 0)) / 100
        for user_id in set(paid_cents) | set(owed_cents)
    }
    transfers = minimize_transfers(balances)
    return SettlementRead(
        balances=[
            BalanceRead(
                user_id=user_id,
                paid_cents=paid_cents.get(user_id, 0),
                owed_cents=owed_cents.get(user_id, 0),
                net_cents=paid_cents.get(user_id, 0) - owed_cents.get(user_id, 0),
            )
            for user_id in sorted(balances, key=str)
        ],
        transfers=[
            TransferRead(from_user=transfer.from_user, to_user=transfer.to_user, amount=transfer.amount)
            for transfer in transfers
        ],
    )


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: UUID,
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> None:
    trip, membership = trip_and_membership
    expense = await session.get(Expense, expense_id)
    if expense is None or expense.trip_id != trip.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if expense.payer_id != membership.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the payer can delete the expense",
        )
    await session.delete(expense)
    await session.commit()
