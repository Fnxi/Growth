"""add infrastructure check runs

Revision ID: e8a61b48f29c
Revises: 95f41424184b
Create Date: 2026-10-31 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e8a61b48f29c"
down_revision: Union[str, Sequence[str], None] = "95f41424184b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "running", "success", "degraded", "failed", "skipped", name="scheduler_run_status", create_type=False
    )
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "infrastructure_check_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", status, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_infrastructure_check_runs_started_at", "infrastructure_check_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_infrastructure_check_runs_started_at", table_name="infrastructure_check_runs")
    op.drop_table("infrastructure_check_runs")
    sa.Enum(name="scheduler_run_status").drop(op.get_bind(), checkfirst=True)
