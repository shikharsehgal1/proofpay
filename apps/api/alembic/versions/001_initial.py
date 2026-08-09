"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("x_user_id", sa.String(64), nullable=False, unique=True),
        sa.Column("x_username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128)),
        sa.Column("profile_image_url", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    # Remaining tables created via metadata.create_all in app lifespan for speed;
    # this revision anchors Alembic. Expand with autogenerate in production.


def downgrade() -> None:
    op.drop_table("users")
