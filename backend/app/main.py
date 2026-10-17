import asyncio
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.router import api_router
from app.core.config import get_settings
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
                await connection.execute(
                    text("ALTER TABLE trip ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT ''")
                )
                await connection.execute(
                    text(
                        "ALTER TABLE trip ADD COLUMN IF NOT EXISTS home_base_label TEXT NOT NULL DEFAULT ''"
                    )
                )
                # Trips created before invite links existed get a token now.
                missing_tokens = (
                    await connection.execute(
                        text("SELECT trip_id FROM trip WHERE invite_token IS NULL")
                    )
                ).all()
                for (trip_id,) in missing_tokens:
                    await connection.execute(
                        text("UPDATE trip SET invite_token = :token WHERE trip_id = :trip_id"),
                        {"token": secrets.token_urlsafe(18), "trip_id": trip_id},
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

# The frontend authenticates with bearer JWTs (no cookies), so credentials are
# not exposed cross-origin; only the listed browser origins are allowed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router)


@app.get("/healthz", tags=["health"])
async def health_check() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok"}
