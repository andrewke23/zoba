"""Trip prep endpoints: the shared task list (F15) and packing list.

Any joined member can add, update, or delete items on either list.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trip_for_member
from app.core.database import get_session
from app.models.entities import Membership, MembershipStatus, PackingItem, Task, Trip
from app.schemas.prep import (
    PackingItemCreate,
    PackingItemRead,
    PackingItemUpdate,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)

router = APIRouter(prefix="/trips/{trip_id}")


def _task_read(task: Task) -> TaskRead:
    return TaskRead(task_id=task.id, trip_id=task.trip_id, title=task.title, due_date=task.due_date, status=task.status)


def _packing_read(item: PackingItem) -> PackingItemRead:
    return PackingItemRead(item_id=item.id, label=item.label, packed=item.packed, assignee_id=item.assignee_id)


async def _task_or_404(session: AsyncSession, trip_id: UUID, task_id: UUID) -> Task:
    task = await session.get(Task, task_id)
    if task is None or task.trip_id != trip_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


async def _packing_or_404(session: AsyncSession, trip_id: UUID, item_id: UUID) -> PackingItem:
    item = await session.get(PackingItem, item_id)
    if item is None or item.trip_id != trip_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


async def _check_assignee(session: AsyncSession, trip_id: UUID, assignee_id: UUID | None) -> None:
    if assignee_id is None:
        return
    joined = await session.scalar(
        select(Membership.user_id).where(
            Membership.trip_id == trip_id,
            Membership.user_id == assignee_id,
            Membership.status == MembershipStatus.JOINED,
        )
    )
    if joined is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee must be a member of this trip."
        )


# Tasks ---------------------------------------------------------------------


@router.get("/tasks", response_model=list[TaskRead])
async def list_tasks(
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[TaskRead]:
    """Tasks by due date, with undated tasks last."""
    trip, _ = access
    tasks = await session.scalars(
        select(Task).where(Task.trip_id == trip.id).order_by(Task.due_date.asc().nulls_last(), Task.title)
    )
    return [_task_read(task) for task in tasks]


@router.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> TaskRead:
    trip, _ = access
    task = Task(trip_id=trip.id, title=payload.title, due_date=payload.due_date, status="open")
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return _task_read(task)


@router.patch("/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> TaskRead:
    trip, _ = access
    task = await _task_or_404(session, trip.id, task_id)
    task.status = payload.status
    await session.commit()
    return _task_read(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> None:
    trip, _ = access
    await session.delete(await _task_or_404(session, trip.id, task_id))
    await session.commit()


# Packing list --------------------------------------------------------------


@router.get("/packing", response_model=list[PackingItemRead])
async def list_packing(
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> list[PackingItemRead]:
    """Items in the order they were added."""
    trip, _ = access
    items = await session.scalars(
        select(PackingItem).where(PackingItem.trip_id == trip.id).order_by(PackingItem.created_at, PackingItem.id)
    )
    return [_packing_read(item) for item in items]


@router.post("/packing", response_model=PackingItemRead, status_code=status.HTTP_201_CREATED)
async def create_packing_item(
    payload: PackingItemCreate,
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> PackingItemRead:
    trip, _ = access
    await _check_assignee(session, trip.id, payload.assignee_id)
    item = PackingItem(trip_id=trip.id, label=payload.label, packed=False, assignee_id=payload.assignee_id)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _packing_read(item)


@router.put("/packing/{item_id}", response_model=PackingItemRead)
async def update_packing_item(
    item_id: UUID,
    payload: PackingItemUpdate,
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> PackingItemRead:
    trip, _ = access
    item = await _packing_or_404(session, trip.id, item_id)
    await _check_assignee(session, trip.id, payload.assignee_id)
    item.label = payload.label
    item.packed = payload.packed
    item.assignee_id = payload.assignee_id
    await session.commit()
    return _packing_read(item)


@router.delete("/packing/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_packing_item(
    item_id: UUID,
    access: tuple[Trip, Membership] = Depends(get_trip_for_member),
    session: AsyncSession = Depends(get_session),
) -> None:
    trip, _ = access
    await session.delete(await _packing_or_404(session, trip.id, item_id))
    await session.commit()
