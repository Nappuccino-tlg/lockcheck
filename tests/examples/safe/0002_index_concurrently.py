"""Adding an index to a table that already has rows, the way that does not block writes."""

from alembic import op


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index("ix_clicks_at", "clicks", ["clicked_at"], postgresql_concurrently=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_clicks_at", table_name="clicks", postgresql_concurrently=True)
