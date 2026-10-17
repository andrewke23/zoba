import asyncio

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.database import get_session
from app.core.security import create_access_token, get_current_user_id
from app.models.entities import User
from app.schemas.auth import AuthToken, UserLogin, UserRead, UserRegister

router = APIRouter(prefix="/auth")

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)

# bcrypt is CPU-bound and can take hundreds of milliseconds per call, so it
# must never run directly on the event loop: every hashing call is offloaded
# to a worker thread with asyncio.to_thread.
_DUMMY_PLAINTEXT = "zoba-placeholder"
_dummy_password_hash: str | None = None


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Stored value is not valid bcrypt (e.g. a pipeline placeholder row).
        return False


def _verify_against_dummy_hash(password: str) -> bool:
    """Hash against a placeholder so unknown emails cost the same time as real logins.

    Built lazily (and off the event loop) so importing this module stays cheap.
    """
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = bcrypt.hashpw(
            _DUMMY_PLAINTEXT.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")
    return _verify_password(password, _dummy_password_hash)


@router.post("/register", response_model=AuthToken, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, session: AsyncSession = Depends(get_session)) -> AuthToken:
    user = User(
        email=payload.email,
        password_hash=await asyncio.to_thread(_hash_password, payload.password),
        name=payload.name,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        ) from exc
    await session.refresh(user)
    await session.commit()
    return AuthToken(access_token=create_access_token(user.id), user=UserRead.model_validate(user))


@router.post("/login", response_model=AuthToken)
async def login(payload: UserLogin, session: AsyncSession = Depends(get_session)) -> AuthToken:
    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None:
        # Spend the same bcrypt time as a real match to avoid leaking, through
        # response latency, whether the email is registered.
        await asyncio.to_thread(_verify_against_dummy_hash, payload.password)
        raise _INVALID_CREDENTIALS
    if not await asyncio.to_thread(_verify_password, payload.password, user.password_hash):
        raise _INVALID_CREDENTIALS
    return AuthToken(access_token=create_access_token(user.id), user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
async def read_me(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserRead.model_validate(user)
