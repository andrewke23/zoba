from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://zoba:zoba@localhost:5432/zoba"
    jwt_secret_key: str = Field(min_length=32)
    access_token_ttl_minutes: int = Field(default=1440, gt=0)
    # Comma-separated browser origins allowed to call the API directly (the
    # Vite dev server proxies same-origin in dev, so this mainly matters for
    # preview/production builds served from another origin).
    cors_origins: str = "http://localhost:5173,http://localhost:4173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
