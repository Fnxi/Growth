"""add scheduler heartbeat

Revision ID: ba9d803f6c72
Revises: e8a61b48f29c
Create Date: 2026-10-31 20:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ba9d803f6c72"
down_revision: Union[str, Sequence[str], None] = "e8a61b48f29c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "infrastructure_scheduler_heartbeat",
        sa.Column("scheduler_name", sa.String(length=50), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("scheduler_name"),
    )


def downgrade() -> None:
    op.drop_table("infrastructure_scheduler_heartbeat")
