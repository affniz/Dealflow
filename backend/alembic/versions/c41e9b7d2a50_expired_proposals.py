"""expired proposals

Revision ID: c41e9b7d2a50
Revises: 873c3c2832d5
Create Date: 2026-11-24 17:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c41e9b7d2a50"
down_revision: str | Sequence[str] | None = "873c3c2832d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # unused in this transaction, so it can be added inside one (PostgreSQL 12+)
    op.execute("ALTER TYPE proposalstatus ADD VALUE IF NOT EXISTS 'expired'")


def downgrade() -> None:
    # PostgreSQL can't drop an enum value: expired suggestions become failed ones (they keep
    # their reason in `error`), and the type is rebuilt without it
    op.execute("UPDATE agentproposal SET status = 'failed' WHERE status = 'expired'")
    op.execute("ALTER TYPE proposalstatus RENAME TO proposalstatus_old")
    op.execute("CREATE TYPE proposalstatus AS ENUM ('pending', 'approved', 'rejected', 'failed')")
    op.execute(
        "ALTER TABLE agentproposal ALTER COLUMN status TYPE proposalstatus "
        "USING status::text::proposalstatus"
    )
    op.execute("DROP TYPE proposalstatus_old")
