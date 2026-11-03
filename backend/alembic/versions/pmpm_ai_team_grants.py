"""Persist the installation owner's approval of a project team's current members."""

import sqlalchemy as sa
from alembic import op

revision = "pmpm_ai_team_grants"
down_revision = "v199_subcontractor_contact_link"
branch_labels = None
depends_on = None

GRANTS = "oe_ai_company_team_grant"
APPROVALS = "oe_ai_company_team_approval"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(GRANTS):
        op.create_table(
            GRANTS,
            sa.Column(
                "team_id", sa.String(36), sa.ForeignKey("oe_teams_team.id", ondelete="CASCADE"), primary_key=True
            ),
        )
    if not inspector.has_table(APPROVALS):
        op.create_table(
            APPROVALS,
            sa.Column(
                "membership_id",
                sa.String(36),
                sa.ForeignKey("oe_teams_membership.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("team_id", sa.String(36), sa.ForeignKey(f"{GRANTS}.team_id", ondelete="CASCADE"), nullable=False),
        )
        op.create_index(f"ix_{APPROVALS}_team_id", APPROVALS, ["team_id"])


def downgrade() -> None:
    op.drop_table(APPROVALS)
    op.drop_table(GRANTS)
