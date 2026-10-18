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

# Mirrors input_embedding in data-pipeline/db/schema.sql for volumes created
# before the table existed.
_INPUT_EMBEDDING_DDL = (
    """
    CREATE TABLE IF NOT EXISTS input_embedding (
        embedding_id     BIGSERIAL PRIMARY KEY,
        user_id          UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
        trip_id          UUID REFERENCES trip(trip_id) ON DELETE CASCADE,
        input_kind       TEXT NOT NULL,
        source_id        TEXT NOT NULL,
        embedder_version TEXT NOT NULL,
        vector           REAL[] NOT NULL,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS input_embedding_trip_kind_idx ON input_embedding (trip_id, input_kind)",
    "CREATE INDEX IF NOT EXISTS input_embedding_user_idx ON input_embedding (user_id)",
)


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
                for statement in _INPUT_EMBEDDING_DDL:
                    await connection.execute(text(statement))
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
