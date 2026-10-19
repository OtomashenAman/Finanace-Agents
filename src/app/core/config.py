from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Finance Agent Command Center"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False

    database_url: str
    secret_key: SecretStr
    cors_origins: list[str] = []

    # Auth
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    refresh_reuse_grace_seconds: int = 30  # concurrent refreshes from several tabs
    cookie_secure: bool = False  # true whenever served over HTTPS
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # Overview
    review_sla_hours: int = 24

    # Demo seed user (uv run poe seed)
    demo_admin_email: str = "finance.admin@example.com"
    demo_admin_name: str = "Finance Admin"
    demo_admin_password: SecretStr | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Self:
        if self.is_production:
            key = self.secret_key.get_secret_value()
            if len(key) < 32 or key == "change-me":
                raise ValueError("SECRET_KEY must be a random value of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment / .env
