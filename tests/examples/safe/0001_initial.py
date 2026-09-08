"""A migration that locks nothing, kept as a fixture and as documentation.

Everything here happens on tables this migration created, so there is nothing for a lock
to block -- which is the ordinary shape of a first migration.
"""

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
