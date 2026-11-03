"""add nullable tenancy scope to campaign and post roots

Revision ID: f1a9c2d5e8b0
Revises: d8f7a1c4e902
Create Date: 2026-11-03 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a9c2d5e8b0"
down_revision: Union[str, Sequence[str], None] = "d8f7a1c4e902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_campaign_organization",
        "campaigns",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_campaign_organization_id", "campaigns", ["organization_id"])
    op.create_unique_constraint("uq_campaign_id_organization", "campaigns", ["id", "organization_id"])

    op.add_column("posts", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_post_organization",
        "posts",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_post_organization_id", "posts", ["organization_id"])
    op.create_unique_constraint("uq_post_id_organization", "posts", ["id", "organization_id"])

    op.add_column("campaign_posts", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_campaign_post_organization",
        "campaign_posts",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_campaign_posts_organization_id", "campaign_posts", ["organization_id"])
    op.create_foreign_key(
        "fk_campaign_posts_campaign_organization",
        "campaign_posts",
        "campaigns",
        ["campaign_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_campaign_posts_post_organization",
        "campaign_posts",
        "posts",
        ["post_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_campaign_posts_post_organization", "campaign_posts", type_="foreignkey")
    op.drop_constraint("fk_campaign_posts_campaign_organization", "campaign_posts", type_="foreignkey")
    op.drop_index("ix_campaign_posts_organization_id", table_name="campaign_posts")
    op.drop_constraint("fk_campaign_post_organization", "campaign_posts", type_="foreignkey")
    op.drop_column("campaign_posts", "organization_id")

    op.drop_constraint("uq_post_id_organization", "posts", type_="unique")
    op.drop_index("ix_post_organization_id", table_name="posts")
    op.drop_constraint("fk_post_organization", "posts", type_="foreignkey")
    op.drop_column("posts", "organization_id")

    op.drop_constraint("uq_campaign_id_organization", "campaigns", type_="unique")
    op.drop_index("ix_campaign_organization_id", table_name="campaigns")
    op.drop_constraint("fk_campaign_organization", "campaigns", type_="foreignkey")
    op.drop_column("campaigns", "organization_id")
