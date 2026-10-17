import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from geoalchemy2.types import Geography, Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MembershipRole(str, enum.Enum):
    ORGANIZER = "organizer"
    MEMBER = "member"


class MembershipStatus(str, enum.Enum):
    INVITED = "invited"
    JOINED = "joined"
    LEFT = "left"


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column("user_id", Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class City(Base):
    __tablename__ = "city"

    city_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    bbox: Mapped[object] = mapped_column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False)


class Destination(Base):
    __tablename__ = "destination"

    id: Mapped[uuid.UUID] = mapped_column("destination_id", Uuid, primary_key=True)
    admission_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))


class Trip(Base):
    __tablename__ = "trip"
    __table_args__ = (CheckConstraint("end_date >= start_date"), CheckConstraint("day_end > day_start"))

    id: Mapped[uuid.UUID] = mapped_column("trip_id", Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    organizer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("app_user.user_id"), nullable=False)
    city_id: Mapped[str] = mapped_column(String, ForeignKey("city.city_id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_start_time: Mapped[time] = mapped_column("day_start", Time, nullable=False)
    daily_end_time: Mapped[time] = mapped_column("day_end", Time, nullable=False)
    home_base: Mapped[object] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    invite_token: Mapped[str | None] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        CheckConstraint("role IN ('organizer','member')"),
        CheckConstraint("status IN ('invited','joined','left')"),
    )

    trip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("trip.trip_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("app_user.user_id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(
            MembershipRole,
            native_enum=False,
            length=16,
            values_callable=lambda roles: [role.value for role in roles],
        ),
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(
            MembershipStatus,
            native_enum=False,
            length=16,
            values_callable=lambda statuses: [membership_status.value for membership_status in statuses],
        ),
        nullable=False,
        server_default=text("'invited'"),
    )


class ItineraryStop(Base):
    __tablename__ = "itinerary_stop"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("trip.trip_id", ondelete="CASCADE"), primary_key=True
    )
    day_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    seq: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destination.destination_id"), nullable=False
    )
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))


class Expense(Base):
    __tablename__ = "expense"
    __table_args__ = (CheckConstraint("amount_cents > 0"),)

    id: Mapped[uuid.UUID] = mapped_column("expense_id", Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    trip_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("trip.trip_id", ondelete="CASCADE"), nullable=False)
    payer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("app_user.user_id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ExpenseShare(Base):
    __tablename__ = "expense_share"
    __table_args__ = (CheckConstraint("share_cents >= 0"),)

    expense_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("expense.expense_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("app_user.user_id"), primary_key=True)
    share_cents: Mapped[int] = mapped_column(Integer, nullable=False)
