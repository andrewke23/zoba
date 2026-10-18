import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.router import api_router
from app.core.database import engine

_STARTUP_MIGRATION_ATTEMPTS = 5
_STARTUP_MIGRATION_BASE_DELAY_SECONDS = 2.0


async def _apply_startup_migrations() -> None:
    """Run additive schema fixes.

    Retries with backoff: the database can accept TCP connections (passing the
    compose healthcheck) a moment before it stops rejecting queries during
    Postgres startup recovery, which would otherwise crash the application.
    """
    for attempt in range(1, _STARTUP_MIGRATION_ATTEMPTS + 1):
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT ''")
                )
            return
        except DBAPIError:
            if attempt == _STARTUP_MIGRATION_ATTEMPTS:
                raise
            await asyncio.sleep(_STARTUP_MIGRATION_BASE_DELAY_SECONDS * attempt)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await _apply_startup_migrations()
    yield
    await engine.dispose()


app = FastAPI(title="Zoba Backend API", version="1.0.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/healthz", tags=["health"])
async def health_check() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok"}
