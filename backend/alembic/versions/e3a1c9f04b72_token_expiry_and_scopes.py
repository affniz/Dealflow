"""token expiry and scopes

Revision ID: e3a1c9f04b72
Revises: c41e9b7d2a50
Create Date: 2026-11-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3a1c9f04b72"
down_revision: str | Sequence[str] | None = "c41e9b7d2a50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tokens made before this could always propose changes and never expired: they keep what
    # they could do, and stop working 90 days from now unless they're replaced.
    op.add_column(
        "apitoken",
        sa.Column(
            "scope",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
            server_default="suggest",
        ),
    )
    op.alter_column("apitoken", "scope", server_default=None)
    op.add_column(
        "apitoken", sa.Column("expires_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True)
    )
    op.execute("UPDATE apitoken SET expires_at = now() + interval '90 days'")
    op.alter_column("apitoken", "expires_at", nullable=False)


def downgrade() -> None:
    op.drop_column("apitoken", "expires_at")
    op.drop_column("apitoken", "scope")
