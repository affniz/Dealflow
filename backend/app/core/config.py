from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEV_SECRET = "dev-only-insecure-secret-change-me-before-deploying"
DEV_OWNER_PASSWORD = "changethis123"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    PROJECT_NAME: str = "Dealflow"
    ENVIRONMENT: Literal["local", "production"] = "local"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = DEV_SECRET
    # Sign-in sessions (app.services.auth): one ends after this long unused, and after
    # SESSION_MAX_DAYS however much it's used. Signing out, changing your password or being
    # deactivated ends sessions straight away.
    SESSION_IDLE_MINUTES: int = 60 * 12
    SESSION_MAX_DAYS: int = 7
    # Failed sign-ins allowed within LOGIN_WINDOW_MINUTES, per email from one address and in
    # all from one address, before that address has to wait.
    LOGIN_WINDOW_MINUTES: int = 15
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_MAX_FAILURES_PER_IP: int = 30

    # Password reset emails (app.services.password_reset). Without SMTP, people get a reset
    # link from an admin instead; while developing, the link is written to the API's log.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_STARTTLS: bool = True  # false: SMTP over TLS from the start (usually port 465)
    EMAILS_FROM: str | None = None  # e.g. "Dealflow <dealflow@example.com>"
    # The app's public address, for links in emails (Render sets RENDER_EXTERNAL_URL). Never
    # taken from the request: a forged Host header would point the link somewhere else.
    APP_URL: str | None = Field(
        default=None, validation_alias=AliasChoices("APP_URL", "RENDER_EXTERNAL_URL")
    )

    DATABASE_URL: str = "postgresql+psycopg://dealflow:dealflow@localhost:5432/dealflow"
    # used by pytest; tables are created fresh in it, so never point this at real data
    TEST_DATABASE_URL: str = "postgresql+psycopg://dealflow:dealflow@localhost:5432/dealflow_test"

    REDIS_URL: str = "redis://localhost:6379/0"
    ROTTING_CHECK_INTERVAL_SECONDS: int = 3600

    FIRST_OWNER_EMAIL: str = "owner@example.com"
    FIRST_OWNER_PASSWORD: str = DEV_OWNER_PASSWORD

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    # The built React app (frontend/dist). When set, the API serves it too, from the same
    # address, so the deployed app is one service (the Docker image sets this).
    STATIC_DIR: str | None = None
    # Public demo: loads the demo team on start, offers one-click demo sign-in, and refuses
    # changes that would lock other visitors out or raise AI spending (passwords, users, AI
    # settings and budgets).
    DEMO_MODE: bool = False
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

    @field_validator("DATABASE_URL", "TEST_DATABASE_URL")
    @classmethod
    def _use_psycopg(cls, url: str) -> str:
        # Hosts (Render, Railway, Heroku) hand out postgres:// or postgresql:// URLs
        for scheme in ("postgres://", "postgresql://"):
            if url.startswith(scheme):
                return "postgresql+psycopg://" + url.removeprefix(scheme)
        return url

    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM and self.APP_URL)

    @property
    def password_reset_by_email(self) -> bool:
        """Whether "Forgot your password?" works: by email, or (developing) via the log."""
        return self.emails_enabled or self.ENVIRONMENT == "local"

    @model_validator(mode="after")
    def _no_dev_secrets_in_prod(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY == DEV_SECRET:
                raise ValueError("Set SECRET_KEY before running in production")
            if self.FIRST_OWNER_PASSWORD == DEV_OWNER_PASSWORD:
                raise ValueError("Set FIRST_OWNER_PASSWORD before running in production")
        return self


settings = Settings()
