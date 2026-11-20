from decimal import Decimal
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEV_SECRET = "dev-only-insecure-secret-change-me-before-deploying"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    PROJECT_NAME: str = "Dealflow"
    ENVIRONMENT: Literal["local", "production"] = "local"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = DEV_SECRET
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    DATABASE_URL: str = "postgresql+psycopg://dealflow:dealflow@localhost:5432/dealflow"
    # used by pytest; tables are created fresh in it, so never point this at real data
    TEST_DATABASE_URL: str = "postgresql+psycopg://dealflow:dealflow@localhost:5432/dealflow_test"

    REDIS_URL: str = "redis://localhost:6379/0"
    ROTTING_CHECK_INTERVAL_SECONDS: int = 3600

    FIRST_OWNER_EMAIL: str = "owner@example.com"
    FIRST_OWNER_PASSWORD: str = "changethis123"

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    DEFAULT_CURRENCY: str = "INR"
    # the team's time zone: what "today" and "10am" mean to the AI agents
    TIMEZONE: str = "Asia/Kolkata"

    # AI agents (Claude Messages API). Without a key, AI features report they're not set up.
    ANTHROPIC_API_KEY: str | None = None
    # False turns the AI agents off even if credentials are around (end-to-end tests, CI)
    AI_ENABLED: bool = True
    # Defaults for each agent; admins can change them in Settings (stored in the database).
    COPILOT_MODEL: str = "claude-sonnet-5-5"
    COPILOT_EFFORT: Effort = "medium"
    PIPELINE_MODEL: str = "claude-sonnet-5-5"
    PIPELINE_EFFORT: Effort = "medium"

    # Monthly AI budgets in USD (empty = no limit); admins can change them in Settings.
    COPILOT_MONTHLY_BUDGET_USD: Decimal | None = Decimal("10")  # per person
    PIPELINE_MONTHLY_BUDGET_USD: Decimal | None = Decimal("20")  # the whole team
    COPILOT_MAX_STEPS: int = 8  # model calls per user message, to bound cost and latency

    # Pipeline agent: reviews stalled deals every morning and proposes next steps
    PIPELINE_REVIEW_HOUR: int = 7  # local hour (TIMEZONE) for the daily review
    PIPELINE_REVIEW_MAX_DEALS: int = 20  # per run, to bound cost
    PIPELINE_REVIEW_MAX_STEPS: int = 5  # model calls per deal
    PIPELINE_REVIEW_COOLDOWN_DAYS: int = 3  # don't re-review a deal sooner than this

    @model_validator(mode="after")
    def _no_dev_secrets_in_prod(self) -> "Settings":
        if self.ENVIRONMENT == "production" and self.SECRET_KEY == DEV_SECRET:
            raise ValueError("Set SECRET_KEY before running in production")
        return self


settings = Settings()
