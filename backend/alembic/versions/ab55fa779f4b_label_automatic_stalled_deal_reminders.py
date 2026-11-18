"""label automatic stalled-deal reminders

Revision ID: ab55fa779f4b
Revises: 8bc274527e21
Create Date: 2026-11-18 08:43:36.155114

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401  (autogenerate emits sqlmodel types)


# revision identifiers, used by Alembic.
revision: str = 'ab55fa779f4b'
down_revision: Union[str, Sequence[str], None] = '8bc274527e21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# the stalled-deal job's reminder, as created before it was labelled
REMINDERS = """
    type = 'task' AND subject LIKE 'Stalled deal: %%'
    AND body LIKE 'No stage change in %% days. Follow up, or move it to the right stage.'
"""


def upgrade() -> None:
    """Label existing automatic stalled-deal reminders so agents can tell them apart."""
    op.execute(f"UPDATE activity SET via = 'auto_reminder' WHERE via IS NULL AND {REMINDERS}")


def downgrade() -> None:
    op.execute("UPDATE activity SET via = NULL WHERE via = 'auto_reminder'")
