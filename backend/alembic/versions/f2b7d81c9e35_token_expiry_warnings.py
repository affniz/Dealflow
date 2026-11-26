"""token expiry warnings

Revision ID: f2b7d81c9e35
Revises: e3a1c9f04b72
Create Date: 2026-11-26 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b7d81c9e35"
down_revision: str | Sequence[str] | None = "e3a1c9f04b72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "apitoken",
        sa.Column("expiry_warned_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("apitoken", "expiry_warned_at")
