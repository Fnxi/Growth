"""seed metric definitions

Revision ID: 84f7a11be0a0
Revises: 49ec8a5f0041
Create Date: 2026-10-30 18:56:27.526533
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '84f7a11be0a0'
down_revision: Union[str, Sequence[str], None] = '49ec8a5f0041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO metric_definitions (id, name, category, source, limitations, classification)
        VALUES
        ('00000000-0000-0000-0000-000000000101', 'visible_likes', 'public_engagement', 'manual_public_observation', 'Visible count only; not reach, impressions, or unique accounts.', 'observed'),
        ('00000000-0000-0000-0000-000000000102', 'visible_comments', 'public_engagement', 'manual_public_observation', 'Visible count only; not private interactions or sentiment.', 'observed'),
        ('00000000-0000-0000-0000-000000000103', 'first_party_visits', 'first_party_traffic', 'own_tracking_events', 'Calculated from own events; excludes traffic not passing through owned infrastructure.', 'calculated'),
        ('00000000-0000-0000-0000-000000000104', 'first_party_link_clicks', 'first_party_traffic', 'own_tracking_events', 'Calculated from own link events; it does not represent Instagram reach or impressions.', 'calculated')
    """)


def downgrade() -> None:
    op.execute("DELETE FROM metric_definitions WHERE name IN ('visible_likes', 'visible_comments', 'first_party_visits', 'first_party_link_clicks')")
