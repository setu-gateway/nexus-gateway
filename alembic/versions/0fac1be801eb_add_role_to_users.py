"""add role to users

Revision ID: 0fac1be801eb
Revises: 0d423c63d89d
Create Date: 2026-08-02 18:57:23.208040

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0fac1be801eb"
down_revision: str | Sequence[str] | None = "0d423c63d89d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills existing rows: every user today is the sole member of
    # the organization /auth/register created for them, so "owner" is the correct
    # role for pre-existing accounts, not just the default for new ones.
    op.add_column("users", sa.Column("role", sa.String(length=20), nullable=False, server_default="owner"))


def downgrade() -> None:
    op.drop_column("users", "role")
