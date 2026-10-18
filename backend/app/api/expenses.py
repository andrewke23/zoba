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
    ExpenseCreate,
    ExpenseRead,
    ExpenseSplitRead,
    TransferRead,
)
from app.services.embedder import describe_expense, record_input_embedding
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
    await record_input_embedding(
        session,
        user_id=membership.user_id,
        trip_id=trip.id,
        input_kind="expense",
        source_id=str(expense.id),
        text=describe_expense(description=payload.description),
    )
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


@router.get("/settlement", response_model=list[TransferRead])
async def read_settlement(
    trip_and_membership: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[TransferRead]:
    trip, _ = trip_and_membership
    balances: dict[UUID, Decimal] = {
        user_id: Decimal(0)
        for user_id in (
            await session.scalars(
                select(Membership.user_id).where(Membership.trip_id == trip.id)
            )
        ).all()
    }

    payments = await session.execute(
        select(Expense.payer_id, func.sum(Expense.amount_cents))
        .where(Expense.trip_id == trip.id)
        .group_by(Expense.payer_id)
    )
    for user_id, paid_cents in payments:
        balances[user_id] = balances.get(user_id, Decimal(0)) + Decimal(paid_cents) / 100

    owed = await session.execute(
        select(ExpenseShare.user_id, func.sum(ExpenseShare.share_cents))
        .join(Expense, Expense.id == ExpenseShare.expense_id)
        .where(Expense.trip_id == trip.id)
        .group_by(ExpenseShare.user_id)
    )
    for user_id, owed_cents in owed:
        balances[user_id] = balances.get(user_id, Decimal(0)) - Decimal(owed_cents) / 100

    transfers = minimize_transfers(balances)
    return [
        TransferRead(from_user=transfer.from_user, to_user=transfer.to_user, amount=transfer.amount)
        for transfer in transfers
    ]
