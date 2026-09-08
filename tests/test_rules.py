"""One test per rule, plus the cases that separate a real finding from a false one.

A linter is judged on what it does not report. Every rule below has a matching test for
the safe version of the same operation, because a tool that flags the correct code as well
as the dangerous code teaches people to stop reading it.
"""

from pathlib import Path

import pytest

from lockcheck import check_source

HERE = Path("0001_example.py")


def codes(source: str) -> list[str]:
    return [finding.code for finding in check_source(source, HERE)]


def migration(body: str) -> str:
    return f"import sqlalchemy as sa\nfrom alembic import op\n\n\ndef upgrade():\n{body}\n"


# -- LC001: NOT NULL with no default -------------------------------------------------


def test_not_null_column_without_a_default_is_reported():
    assert codes(
        migration("    op.add_column('users', sa.Column('tier', sa.Text(), nullable=False))")
    ) == ["LC001"]


def test_a_nullable_column_is_fine():
    assert codes(migration("    op.add_column('users', sa.Column('tier', sa.Text()))")) == []


def test_not_null_with_a_server_default_is_fine():
    """Postgres 11 and newer store a constant default in the catalogue and touch no rows."""
    source = migration(
        "    op.add_column('users', sa.Column('tier', sa.Text(), nullable=False,\n"
        "                  server_default='free'))"
    )
    assert codes(source) == []


def test_every_column_in_one_call_is_checked():
    source = migration(
        "    op.add_column('users', sa.Column('a', sa.Text(), nullable=False))\n"
        "    op.add_column('users', sa.Column('b', sa.Text(), nullable=False))"
    )
    assert codes(source) == ["LC001", "LC001"]


# -- LC002 / LC003: indexes ----------------------------------------------------------


def test_a_plain_create_index_is_reported():
    assert codes(migration("    op.create_index('ix_users_email', 'users', ['email'])")) == [
        "LC002"
    ]


def test_concurrent_index_outside_a_transaction_block_is_reported():
    """It would fail at runtime rather than lock, which is a failed deploy either way."""
    source = migration(
        "    op.create_index('ix_users_email', 'users', ['email'],\n"
        "                    postgresql_concurrently=True)"
    )
    assert codes(source) == ["LC003"]


def test_concurrent_index_inside_an_autocommit_block_is_fine():
    source = migration(
        "    with op.get_context().autocommit_block():\n"
        "        op.create_index('ix_users_email', 'users', ['email'],\n"
        "                        postgresql_concurrently=True)"
    )
    assert codes(source) == []


def test_a_plain_index_inside_an_autocommit_block_is_still_reported():
    """The block removes the transaction, not the lock."""
    source = migration(
        "    with op.get_context().autocommit_block():\n"
        "        op.create_index('ix_users_email', 'users', ['email'])"
    )
    assert codes(source) == ["LC002"]


def test_dropping_an_index_locks_the_same_way():
    assert codes(migration("    op.drop_index('ix_users_email', 'users')")) == ["LC002"]


def test_a_nested_block_does_not_lose_the_autocommit_context():
    source = migration(
        "    with op.get_context().autocommit_block():\n"
        "        with open('notes.txt') as handle:\n"
        "            op.create_index('ix', 'users', ['email'], postgresql_concurrently=True)"
    )
    assert codes(source) == []


# -- LC004 / LC005: altering a column ------------------------------------------------


def test_setting_not_null_on_an_existing_column_is_reported():
    assert codes(migration("    op.alter_column('users', 'tier', nullable=False)")) == ["LC004"]


def test_relaxing_a_column_to_nullable_is_fine():
    assert codes(migration("    op.alter_column('users', 'tier', nullable=True)")) == []


def test_changing_a_column_type_is_reported():
    assert codes(migration("    op.alter_column('users', 'tier', type_=sa.Text())")) == ["LC005"]


def test_one_call_can_break_two_rules():
    source = migration("    op.alter_column('users', 'tier', type_=sa.Text(), nullable=False)")
    assert codes(source) == ["LC004", "LC005"]


# -- LC006 / LC007: constraints ------------------------------------------------------


def test_a_foreign_key_is_reported():
    source = migration("    op.create_foreign_key('fk', 'links', 'users', ['owner_id'], ['id'])")
    assert codes(source) == ["LC006"]


def test_a_check_constraint_is_reported():
    source = migration("    op.create_check_constraint('ck', 'users', 'tier IS NOT NULL')")
    assert codes(source) == ["LC006"]


def test_a_unique_constraint_is_reported():
    source = migration("    op.create_unique_constraint('uq_users_email', 'users', ['email'])")
    assert codes(source) == ["LC007"]


# -- what is deliberately not reported -----------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        "op.create_table('t', sa.Column('id', sa.Integer(), primary_key=True))",
        "op.drop_table('t')",
        "op.drop_column('users', 'tier')",
        "op.rename_table('a', 'b')",
        "op.bulk_insert(table, [{'id': 1}])",
    ],
)
def test_operations_that_take_no_interesting_lock(call):
    """A new table has no rows to lock and nobody reading it; dropping is metadata.

    drop_column and rename_table break running application code, which is a real problem
    and a different one -- it is about deploy order, not locks, and the README says so
    rather than this tool guessing at it.
    """
    assert codes(migration(f"    {call}")) == []


def test_a_call_on_something_that_is_not_op_is_ignored():
    assert codes(migration("    helper.create_index('ix', 'users', ['email'])")) == []


def test_the_alembic_op_spelling_is_recognised():
    source = "import alembic\n\n\ndef upgrade():\n    alembic.op.create_index('ix', 't', ['c'])\n"
    assert codes(source) == ["LC002"]


def test_sql_inside_op_execute_is_not_inspected():
    """Stated as a test because it is the boundary, not an oversight -- see the README."""
    source = migration("    op.execute('CREATE INDEX ix_users_email ON users (email)')")
    assert codes(source) == []


# -- silencing -----------------------------------------------------------------------


def test_a_bare_ignore_comment_silences_the_line():
    source = migration("    op.create_index('ix', 'users', ['email'])  # lockcheck: ignore")
    assert codes(source) == []


def test_an_ignore_can_name_one_rule():
    source = migration("    op.alter_column('u', 'c', nullable=False)  # lockcheck: ignore[LC004]")
    assert codes(source) == []


def test_naming_a_different_rule_does_not_silence_this_one():
    source = migration("    op.alter_column('u', 'c', nullable=False)  # lockcheck: ignore[LC002]")
    assert codes(source) == ["LC004"]


def test_an_ignore_can_name_several_rules():
    source = migration(
        "    op.alter_column('u', 'c', type_=sa.Text(), nullable=False)"
        "  # lockcheck: ignore[LC004, LC005]"
    )
    assert codes(source) == []


def test_the_comment_may_sit_anywhere_in_a_multi_line_call():
    """Which is where anyone would put it: beside the argument that made it safe."""
    source = migration(
        "    op.create_index(\n        'ix', 'users', ['email'],  # lockcheck: ignore[LC002]\n    )"
    )
    assert codes(source) == []


# -- shape ---------------------------------------------------------------------------


def test_a_finding_knows_where_it_is_and_what_to_do():
    finding = check_source(migration("    op.create_index('ix', 'users', ['email'])"), HERE)[0]
    assert finding.path == HERE
    assert finding.line == 6
    assert "CONCURRENTLY" in finding.summary
    assert "postgresql_concurrently" in finding.detail


def test_findings_come_back_in_file_order():
    source = migration(
        "    op.create_unique_constraint('uq', 'users', ['email'])\n"
        "    op.create_index('ix', 'users', ['email'])"
    )
    lines = [f.line for f in check_source(source, HERE)]
    assert lines == sorted(lines)


def test_downgrade_is_checked_too():
    """A rollback runs when something is already wrong, which is the worst time to block."""
    source = "from alembic import op\n\n\ndef downgrade():\n    op.create_index('ix', 't', ['c'])\n"
    assert codes(source) == ["LC002"]


def test_a_file_that_is_not_python_raises():
    with pytest.raises(SyntaxError):
        check_source("this is not python(", HERE)


# -- a table created in the same migration is not a table anyone is using -------------


def test_an_index_on_a_table_created_here_is_not_reported():
    """The first thing this tool did against a real project was report ten of these.

    Every one was noise: the table was three lines old, empty, and invisible to anything
    else. A linter is read for exactly as long as it is worth reading.
    """
    source = migration(
        "    op.create_table('users', sa.Column('email', sa.Text()))\n"
        "    op.create_index('ix_users_email', 'users', ['email'])"
    )
    assert codes(source) == []


def test_an_index_on_a_table_from_an_earlier_migration_is_still_reported():
    source = migration("    op.create_index('ix_clicks_at', 'clicks', ['clicked_at'])")
    assert codes(source) == ["LC002"]


def test_dropping_an_index_on_a_table_being_dropped_is_not_reported():
    source = (
        "from alembic import op\n\n\ndef downgrade():\n"
        "    op.drop_index('ix_users_email', table_name='users')\n"
        "    op.drop_table('users')\n"
    )
    assert codes(source) == []


def test_a_not_null_column_added_to_a_table_created_here_is_fine():
    source = migration(
        "    op.create_table('users', sa.Column('id', sa.Integer()))\n"
        "    op.add_column('users', sa.Column('tier', sa.Text(), nullable=False))"
    )
    assert codes(source) == []


def test_a_foreign_key_is_only_safe_when_both_tables_are_new():
    """It locks both ends, so one pre-existing table is enough to make it expensive."""
    both_new = migration(
        "    op.create_table('links')\n"
        "    op.create_table('users')\n"
        "    op.create_foreign_key('fk', 'links', 'users', ['owner_id'], ['id'])"
    )
    assert codes(both_new) == []

    one_old = migration(
        "    op.create_table('links')\n"
        "    op.create_foreign_key('fk', 'links', 'users', ['owner_id'], ['id'])"
    )
    assert codes(one_old) == ["LC006"]


def test_a_table_named_by_a_variable_is_treated_as_pre_existing():
    """Unreadable statically, so it gets the cautious answer: reporting something harmless
    costs a moment, staying quiet about a real lock costs an outage."""
    source = migration(
        "    op.create_table('users')\n"
        "    name = 'users'\n"
        "    op.create_index('ix', name, ['email'])"
    )
    assert codes(source) == ["LC002"]


def test_freshness_does_not_leak_between_functions():
    """upgrade() creating a table says nothing about what downgrade() is touching."""
    source = (
        "from alembic import op\n\n\n"
        "def upgrade():\n    op.create_table('users')\n\n\n"
        "def downgrade():\n    op.create_index('ix', 'users', ['email'])\n"
    )
    assert codes(source) == ["LC002"]
