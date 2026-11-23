from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://zoba:zoba@localhost:5432/zoba"
    jwt_secret_key: str = Field(min_length=32)
    access_token_ttl_minutes: int = Field(default=1440, gt=0)
    # fastembed model used for input embeddings (app/services/embedder.py).
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # OSRM servers for road-network travel times (app/services/routing.py).
    # Defaults are the free FOSSGIS servers (fair use, low volume only); point
    # these at a self-hosted osrm-backend for production.
    routing_foot_url: str = "https://routing.openstreetmap.de/routed-foot"
    routing_car_url: str = "https://routing.openstreetmap.de/routed-car"


@lru_cache
def get_settings() -> Settings:
    return Settings()
