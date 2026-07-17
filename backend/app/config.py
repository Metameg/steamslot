from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://steamslot:steamslot@localhost:5432/steamslot"
    test_database_url: str = (
        "postgresql+psycopg://steamslot:steamslot@localhost:5432/steamslot_test"
    )
    steam_api_base: str = "https://store.steampowered.com/api"
    session_ttl_days: int = 30
    session_cookie_name: str = "steamslot_session"
    cookie_secure: bool = False
    cors_allow_origins: list[str] = ["http://localhost:5173"]
    rate_limit_storage_uri: str = "memory://"
    rate_limit_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
