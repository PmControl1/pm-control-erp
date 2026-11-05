"""Workspace AI (one owner-set provider for everyone) and per-user assistant memory.

Revision ID: v200_workspace_ai_and_memory
Revises: v199_subcontractor_contact_link
"""

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision = "v200_workspace_ai_and_memory"
down_revision = "v199_subcontractor_contact_link"
branch_labels = None
depends_on = None

CONFIG = "oe_ai_workspace_config"
MEMORY = "oe_ai_memory"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(CONFIG):
        op.create_table(
            CONFIG,
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("provider", sa.String(50), nullable=False),
            sa.Column("model", sa.String(200), nullable=False, server_default=""),
            sa.Column("api_key", sa.String(1000), nullable=True),
            sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_by", GUID(), nullable=True),
            *_timestamps(),
        )
    if not inspector.has_table(MEMORY):
        op.create_table(
            MEMORY,
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("user_id", GUID(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="user"),
            *_timestamps(),
        )
        op.create_index(f"ix_{MEMORY}_user_id", MEMORY, ["user_id"])


def downgrade() -> None:
    op.drop_table(MEMORY)
    op.drop_table(CONFIG)
