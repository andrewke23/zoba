from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://zoba:zoba@localhost:5432/zoba"
    jwt_secret_key: str = Field(min_length=32)


@lru_cache
def get_settings() -> Settings:
    return Settings()
