"""One of each, so a rule that stops matching real Alembic output is noticed.

Every call here touches a table from an earlier migration, which is what makes them
expensive -- the same lines against a table created above would be free.
"""

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.add_column("users", sa.Column("tier", sa.Text(), nullable=False))  # LC001
    op.create_index("ix_users_tier", "users", ["tier"])  # LC002
    op.create_index("ix_users_email", "users", ["email"], postgresql_concurrently=True)  # LC003
    op.alter_column("users", "nickname", nullable=False)  # LC004
    op.alter_column("users", "bio", type_=sa.Text())  # LC005
    op.create_foreign_key("fk_links_owner", "links", "users", ["owner_id"], ["id"])  # LC006
    op.create_unique_constraint("uq_users_email", "users", ["email"])  # LC007
