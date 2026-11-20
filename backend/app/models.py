"""Database tables and API schemas.

Each resource follows the same pattern:
  XBase    shared fields
  X        the table (table=True)
  XCreate  request body for POST
  XUpdate  request body for PATCH (every field optional; required columns reject null)
  XPublic  response body
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, EmailStr, computed_field, field_validator
from pydantic import Field as PydField
from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime | None) -> datetime | None:
    """Treat timestamps sent without a timezone as UTC; store everything in UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def json_column() -> Any:
    return Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    data: list[T]
    count: int


class NamedRef(BaseModel):
    """A linked record's id and display name, so clients don't need extra lookups."""

    id: int
    name: str


class Message(BaseModel):
    message: str


# ---------------------------------------------------------------- enums


class Role(StrEnum):
    owner = "owner"  # everything, including managing admins
    admin = "admin"  # all records, settings, users
    agent = "agent"  # only their own records
    viewer = "viewer"  # read-only, all records


class DealStatus(StrEnum):
    open = "open"
    won = "won"
    lost = "lost"


class ActivityType(StrEnum):
    call = "call"
    meeting = "meeting"
    task = "task"
    email = "email"
    note = "note"


# ---------------------------------------------------------------- users


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    role: Role = Role.agent
    is_active: bool = True


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=utcnow)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(SQLModel):
    email: EmailStr = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    role: Role = None
    is_active: bool = None
    password: str = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)


class PasswordChange(SQLModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UserDirectoryEntry(BaseModel):
    id: int
    name: str
    role: Role


class UserPublic(UserBase):
    id: int
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------- companies


class CompanyBase(SQLModel):
    name: str = Field(min_length=1, max_length=255, index=True)
    domain: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)


class Company(CompanyBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    custom_fields: dict[str, Any] = json_column()
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CompanyCreate(CompanyBase):
    owner_id: int | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class CompanyUpdate(SQLModel):
    name: str = Field(default=None, min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    owner_id: int = None
    custom_fields: dict[str, Any] = None


class CompanyPublic(CompanyBase):
    id: int
    owner_id: int
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    # filled in by app.services.names.with_company_details; counts only cover records the
    # reader can see
    owner: NamedRef | None = None
    contact_count: int = 0
    open_deal_count: int = 0
    open_deal_value: Decimal = Decimal("0")


# ---------------------------------------------------------------- contacts


class ContactBase(SQLModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=255, index=True)
    phone: str | None = Field(default=None, max_length=50)
    job_title: str | None = Field(default=None, max_length=100)
    company_id: int | None = Field(default=None, foreign_key="company.id", index=True)


class Contact(ContactBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    custom_fields: dict[str, Any] = json_column()
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ContactCreate(ContactBase):
    owner_id: int | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class ContactUpdate(SQLModel):
    first_name: str = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    job_title: str | None = Field(default=None, max_length=100)
    company_id: int | None = None
    owner_id: int = None
    custom_fields: dict[str, Any] = None


class ContactPublic(ContactBase):
    id: int
    owner_id: int
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    # filled in by app.services.names.with_contact_details
    owner: NamedRef | None = None
    company: NamedRef | None = None
    open_deal_count: int = 0


# ---------------------------------------------------------------- pipelines


class StageBase(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    position: int = Field(default=0, ge=0)
    probability: int = Field(default=0, ge=0, le=100, description="Win chance, percent")


class Stage(StageBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    pipeline_id: int = Field(foreign_key="pipeline.id", index=True)
    pipeline: "Pipeline" = Relationship(back_populates="stages")


class StageCreate(StageBase):
    pass


class StageUpdate(SQLModel):
    name: str = Field(default=None, min_length=1, max_length=100)
    position: int = Field(default=None, ge=0)
    probability: int = Field(default=None, ge=0, le=100)


class StagePublic(StageBase):
    id: int
    pipeline_id: int


class PipelineBase(SQLModel):
    name: str = Field(min_length=1, max_length=100, unique=True)
    rotting_days: int = Field(
        default=14, ge=1, description="Days without a stage change before a deal is rotting"
    )


class Pipeline(PipelineBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    stages: list[Stage] = Relationship(
        back_populates="pipeline", sa_relationship_kwargs={"order_by": "Stage.position"}
    )


class PipelineCreate(PipelineBase):
    stages: list[StageCreate] = Field(default_factory=list)


class PipelineUpdate(SQLModel):
    name: str = Field(default=None, min_length=1, max_length=100)
    rotting_days: int = Field(default=None, ge=1)


class PipelinePublic(PipelineBase):
    id: int
    created_at: datetime
    stages: list[StagePublic]


class LostReasonBase(SQLModel):
    label: str = Field(min_length=1, max_length=100, unique=True)
    is_active: bool = True


class LostReason(LostReasonBase, table=True):
    id: int | None = Field(default=None, primary_key=True)


class LostReasonCreate(LostReasonBase):
    pass


class StageOrder(SQLModel):
    """Every stage id of a pipeline, in the order they should appear."""

    stage_ids: list[int] = Field(min_length=1)


class LostReasonUpdate(SQLModel):
    label: str = Field(default=None, min_length=1, max_length=100)
    is_active: bool = None


class LostReasonPublic(LostReasonBase):
    id: int


# ---------------------------------------------------------------- deals


class DealBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    value: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    expected_close_date: date | None = None
    contact_id: int | None = Field(default=None, foreign_key="contact.id", index=True)
    company_id: int | None = Field(default=None, foreign_key="company.id", index=True)


class Deal(DealBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    pipeline_id: int = Field(foreign_key="pipeline.id", index=True)
    stage_id: int = Field(foreign_key="stage.id", index=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    status: DealStatus = Field(default=DealStatus.open, index=True)
    lost_reason_id: int | None = Field(default=None, foreign_key="lostreason.id")
    lost_note: str | None = None
    closed_at: datetime | None = None
    stage_changed_at: datetime = Field(default_factory=utcnow)
    # set by the rotting job when an open deal sits in one stage longer than
    # pipeline.rotting_days; cleared when the deal moves or closes
    rotting_since: datetime | None = Field(default=None, index=True)
    custom_fields: dict[str, Any] = json_column()
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DealCreate(DealBase):
    stage_id: int
    owner_id: int | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class DealUpdate(SQLModel):
    title: str = Field(default=None, min_length=1, max_length=255)
    value: Decimal = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default=None, min_length=3, max_length=3)
    expected_close_date: date | None = None
    contact_id: int | None = None
    company_id: int | None = None
    stage_id: int = None
    owner_id: int = None
    custom_fields: dict[str, Any] = None


class DealLost(SQLModel):
    lost_reason_id: int
    note: str | None = Field(default=None, max_length=2000)


class DealPublic(DealBase):
    id: int
    pipeline_id: int
    stage_id: int
    owner_id: int
    status: DealStatus
    lost_reason_id: int | None
    lost_note: str | None
    closed_at: datetime | None
    stage_changed_at: datetime
    rotting_since: datetime | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_rotting(self) -> bool:
        return self.rotting_since is not None

    # filled in by app.services.names.with_deal_names
    owner: NamedRef | None = None
    contact: NamedRef | None = None
    company: NamedRef | None = None


class DealEvent(SQLModel, table=True):
    """Change history for a deal; feeds the deal timeline."""

    id: int | None = Field(default=None, primary_key=True)
    deal_id: int = Field(foreign_key="deal.id", index=True)
    actor_id: int | None = Field(default=None, foreign_key="user.id")
    kind: str = Field(max_length=30)  # created, updated, stage_changed, won, lost, reopened
    data: dict[str, Any] = json_column()
    created_at: datetime = Field(default_factory=utcnow, index=True)


class DealEventPublic(SQLModel):
    id: int
    deal_id: int
    actor_id: int | None
    kind: str
    data: dict[str, Any]
    created_at: datetime


# ---------------------------------------------------------------- activities


class ActivityBase(SQLModel):
    type: ActivityType
    subject: str = Field(min_length=1, max_length=255)
    body: str | None = None
    due_at: datetime | None = None
    deal_id: int | None = Field(default=None, foreign_key="deal.id", index=True)
    contact_id: int | None = Field(default=None, foreign_key="contact.id", index=True)
    company_id: int | None = Field(default=None, foreign_key="company.id", index=True)

    @field_validator("due_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return to_utc(v)


class Activity(ActivityBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    via: str | None = Field(default=None, max_length=30)  # set when an AI agent added it
    done: bool = False
    done_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class ActivityCreate(ActivityBase):
    owner_id: int | None = None
    done: bool = False


class ActivityUpdate(SQLModel):
    type: ActivityType = None
    subject: str = Field(default=None, min_length=1, max_length=255)
    body: str | None = None
    due_at: datetime | None = None
    deal_id: int | None = None
    contact_id: int | None = None
    company_id: int | None = None
    owner_id: int = None
    done: bool = None

    @field_validator("due_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return to_utc(v)


class ActivityPublic(ActivityBase):
    id: int
    owner_id: int
    via: str | None = None
    done: bool
    done_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # filled in by app.services.names.with_activity_names
    owner: NamedRef | None = None
    deal: NamedRef | None = None
    contact: NamedRef | None = None
    company: NamedRef | None = None


# ---------------------------------------------------------------- timeline & dashboard


class TimelineItem(BaseModel):
    kind: Literal["event", "activity"]
    at: datetime
    event: DealEventPublic | None = None
    activity: ActivityPublic | None = None
    # who made the change (events) or owns the activity; None for automated events
    actor: NamedRef | None = None


class StageSummary(BaseModel):
    stage_id: int
    name: str
    probability: int
    deal_count: int
    total_value: Decimal
    weighted_value: Decimal


class PipelineSummary(BaseModel):
    pipeline_id: int
    name: str
    stages: list[StageSummary]
    open_count: int
    open_value: Decimal
    weighted_value: Decimal
    rotting_count: int = 0  # open deals flagged as stalled
    # won and lost deals: all time, or closed since `since` when a period was asked for
    since: datetime | None = None
    won_count: int
    won_value: Decimal
    lost_count: int
    lost_value: Decimal = Decimal("0.00")
    win_rate: float | None = None  # won / (won + lost), 0..1; None when nothing closed


class BoardColumn(BaseModel):
    stage: StagePublic
    deal_count: int
    total_value: Decimal
    weighted_value: Decimal
    rotting_count: int
    deals: list[DealPublic]  # newest first, capped by deals_per_stage


class Board(BaseModel):
    pipeline_id: int
    name: str
    rotting_days: int
    columns: list[BoardColumn]
    total_value: Decimal
    weighted_value: Decimal


class LostReasonStat(BaseModel):
    reason_id: int
    label: str
    count: int
    value: Decimal
    share: float  # fraction of lost deals, 0..1


class LostReasonReport(BaseModel):
    since: datetime
    lost_count: int
    lost_value: Decimal
    reasons: list[LostReasonStat]  # most common first


# ---------------------------------------------------------------- AI agents


class AgentConversation(SQLModel, table=True):
    """A Copilot chat. `messages` is the exact Messages API history and is only ever appended
    to: the model's thinking blocks are only valid in an unedited conversation."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str = Field(max_length=120)
    messages: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    # fixed when the chat starts: switching model or effort mid-conversation would lose the
    # prompt cache and the earlier turns' thinking
    model: str | None = Field(default=None, max_length=100)
    effort: str | None = Field(default=None, max_length=10)
    prompt_version: int | None = None  # app.agent.copilot.PROMPTS key; fixed like the model
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class RunStatus(StrEnum):
    completed = "completed"
    failed = "failed"


class AgentRun(SQLModel, table=True):
    """One autonomous agent review of one deal, kept for the inbox and for auditing."""

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(max_length=30)  # "pipeline_review"
    deal_id: int | None = Field(default=None, foreign_key="deal.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)  # whose access it ran with
    status: RunStatus = Field(index=True)
    summary: str | None = None  # the agent's note to the owner
    error: str | None = None
    messages: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime = Field(default_factory=utcnow, index=True)


class AgentRunPublic(SQLModel):
    id: int
    kind: str
    deal_id: int | None
    deal: NamedRef | None = None
    user_id: int
    status: RunStatus
    summary: str | None
    error: str | None
    proposal_count: int = 0
    created_at: datetime


class ProposalStatus(StrEnum):
    pending = "pending"
    approved = "approved"  # approved and applied
    rejected = "rejected"
    failed = "failed"  # approved, but applying it failed (e.g. the deal changed meanwhile)


class AgentProposal(SQLModel, table=True):
    """A change an agent wants to make. Nothing happens until a person approves it."""

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(max_length=30)  # "copilot" or "pipeline_agent"
    conversation_id: int | None = Field(default=None, foreign_key="agentconversation.id")
    run_id: int | None = Field(default=None, foreign_key="agentrun.id", index=True)
    tool_use_id: str | None = Field(default=None, max_length=100, index=True)
    # the person it acts for; they (or an admin) approve it, and it runs with their access
    user_id: int = Field(foreign_key="user.id", index=True)
    deal_id: int | None = Field(default=None, foreign_key="deal.id", index=True)
    action: str = Field(max_length=50)
    params: dict[str, Any] = json_column()
    summary: str = Field(max_length=500)
    rationale: str | None = Field(default=None, max_length=2000)
    status: ProposalStatus = Field(default=ProposalStatus.pending, index=True)
    error: str | None = None
    decided_by_id: int | None = Field(default=None, foreign_key="user.id")
    decided_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)


class AgentProposalPublic(SQLModel):
    id: int
    source: str
    conversation_id: int | None
    run_id: int | None = None
    user_id: int
    deal_id: int | None
    deal: NamedRef | None = None
    action: str
    summary: str
    rationale: str | None
    status: ProposalStatus
    error: str | None
    decided_by_id: int | None
    decided_at: datetime | None
    created_at: datetime


class CopilotMessageIn(BaseModel):
    conversation_id: int | None = None
    text: str = PydField(min_length=1, max_length=4000)
    deal_id: int | None = PydField(
        default=None, description="The deal the user is looking at, for context"
    )


class ChatItem(BaseModel):
    kind: Literal["user", "assistant", "step"]
    text: str
    proposal_id: int | None = None


class ConversationView(BaseModel):
    id: int
    title: str
    model: str | None = None
    items: list[ChatItem]
    proposals: list[AgentProposalPublic]
    updated_at: datetime


class ConversationSummary(BaseModel):
    id: int
    title: str
    updated_at: datetime


class AIUsage(SQLModel, table=True):
    """One model's share of one Claude API call: what was used and what it cost.

    A call that falls back to another model produces one row per model that ran.
    """

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    feature: str = Field(max_length=30, index=True)  # "copilot" or "pipeline_agent"
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    turn_id: str = Field(max_length=32, index=True)  # one Copilot question or one deal review
    conversation_id: int | None = Field(default=None, foreign_key="agentconversation.id")
    run_id: int | None = Field(default=None, foreign_key="agentrun.id")
    model: str = Field(max_length=100)
    request_id: str | None = Field(default=None, max_length=100)
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal | None = Field(default=None, max_digits=12, decimal_places=6)


class UsageTotals(BaseModel):
    cost_usd: Decimal
    calls: int
    units: int  # Copilot questions or deal reviews
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int


class FeatureUsage(UsageTotals):
    feature: str
    avg_cost_per_unit: Decimal | None


class ModelUsage(UsageTotals):
    model: str


class UserUsage(BaseModel):
    user: NamedRef | None  # None: the user was deleted
    copilot_cost_usd: Decimal
    pipeline_cost_usd: Decimal
    copilot_questions: int


class DailyUsage(BaseModel):
    date: date
    cost_usd: Decimal


class Budgets(BaseModel):
    """Monthly AI spending limits in USD; None means no limit."""

    copilot_per_person_usd: Decimal | None = PydField(
        default=None, ge=0, le=10000, decimal_places=2
    )
    pipeline_team_usd: Decimal | None = PydField(default=None, ge=0, le=10000, decimal_places=2)


class BudgetStatus(BaseModel):
    budget_usd: Decimal | None
    spent_usd: Decimal
    used_pct: int | None


class UsageSummary(BaseModel):
    month: str  # YYYY-MM in the team's time zone
    prices_as_of: str
    total: UsageTotals
    by_feature: list[FeatureUsage]
    by_model: list[ModelUsage]
    by_user: list[UserUsage]
    daily: list[DailyUsage]
    unpriced_calls: int  # calls to models missing from the price table
    copilot_budget_per_person_usd: Decimal | None = None
    pipeline_budget: BudgetStatus | None = None


class MyUsage(BaseModel):
    month: str
    cost_usd: Decimal
    questions: int
    budget_usd: Decimal | None = None  # this person's Copilot limit; None: no limit
    budget_used_pct: int | None = None
    resets_on: date | None = None


class AppSetting(SQLModel, table=True):
    """Team-wide settings admins change in the app (the environment provides defaults)."""

    key: str = Field(primary_key=True, max_length=100)
    value: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)
    updated_by_id: int | None = Field(default=None, foreign_key="user.id")


EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]


class AISettings(BaseModel):
    copilot_model: str
    copilot_effort: EffortLevel
    pipeline_model: str
    pipeline_effort: EffortLevel


class AISettingsUpdate(BaseModel):
    copilot_model: str | None = None
    copilot_effort: EffortLevel | None = None
    pipeline_model: str | None = None
    pipeline_effort: EffortLevel | None = None


class ModelOption(BaseModel):
    id: str
    name: str
    note: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal


class AISettingsView(BaseModel):
    settings: AISettings
    models: list[ModelOption]
    efforts: list[EffortLevel]
