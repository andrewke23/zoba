"""Trip prep payloads: tasks (F15) and the packing list, in the shapes of frontend/src/api/types.ts."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

TaskStatus = Literal["open", "done"]


def _strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class TaskRead(BaseModel):
    task_id: UUID
    trip_id: UUID
    title: str
    due_date: date | None
    status: TaskStatus
    # Booking tasks generated from the itinerary (F15) need a booking flag the
    # destination catalog doesn't have yet, so every task is manual for now.
    destination_id: UUID | None = None
    auto_generated: bool = False
    booking_url: str | None = None


class TaskCreate(BaseModel):
    title: str = Field(max_length=200)
    due_date: date | None = None

    _title = field_validator("title")(_strip_required)


class TaskUpdate(BaseModel):
    status: TaskStatus


class PackingItemRead(BaseModel):
    item_id: UUID
    label: str
    packed: bool
    # None means everyone brings their own.
    assignee_id: UUID | None


class PackingItemCreate(BaseModel):
    label: str = Field(max_length=200)
    assignee_id: UUID | None = None

    _label = field_validator("label")(_strip_required)


class PackingItemUpdate(PackingItemCreate):
    packed: bool
