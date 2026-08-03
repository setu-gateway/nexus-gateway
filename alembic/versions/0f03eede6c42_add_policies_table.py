"""add policies table

Revision ID: 0f03eede6c42
Revises: 0fac1be801eb
Create Date: 2026-08-03 16:38:56.427391

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0f03eede6c42"
down_revision: str | Sequence[str] | None = "0fac1be801eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("policy_type", sa.String(length=30), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_policies_organization_id"), "policies", ["organization_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_policies_organization_id"), table_name="policies")
    op.drop_table("policies")
