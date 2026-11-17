from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-insecure-secret-change-me-before-deploying"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    PROJECT_NAME: str = "CRM"
    ENVIRONMENT: Literal["local", "production"] = "local"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = DEV_SECRET
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # sqlite for quick local dev; use postgresql+psycopg://user:pass@host/db for real use
    DATABASE_URL: str = "sqlite:///./crm.db"

    FIRST_OWNER_EMAIL: str = "owner@example.com"
    FIRST_OWNER_PASSWORD: str = "changethis123"

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    DEFAULT_CURRENCY: str = "INR"

    @model_validator(mode="after")
    def _no_dev_secrets_in_prod(self) -> "Settings":
        if self.ENVIRONMENT == "production" and self.SECRET_KEY == DEV_SECRET:
            raise ValueError("Set SECRET_KEY before running in production")
        return self


settings = Settings()
