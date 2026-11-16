"""Import recipes: how each spreadsheet layout is read, kept for its next file.

Revision ID: v201_boq_import_recipes
Revises: v200_workspace_ai_and_memory
"""

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision = "v201_boq_import_recipes"
down_revision = "v200_workspace_ai_and_memory"
branch_labels = None
depends_on = None

TABLE = "oe_boq_import_recipe"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("layout_key", sa.String(64), nullable=False),
        sa.Column("recipe", sa.JSON(), nullable=False),
        sa.Column("sheet_names", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="ai"),
        sa.Column("file_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_by", GUID(), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(f"ix_{TABLE}_layout_key", TABLE, ["layout_key"], unique=True)


def downgrade() -> None:
    op.drop_table(TABLE)
