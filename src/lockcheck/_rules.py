"""What each rule is about, and what to do instead.

A linter that only says "this is bad" gets silenced. Every rule here carries the fix,
because the person reading it is usually about to ship and wants the next line to type,
not a research project.

Lock names are Postgres's own. ACCESS EXCLUSIVE blocks everything including SELECT; SHARE
blocks writes but not reads. The difference between an outage and a slow deploy is usually
which of those a migration takes and for how long.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    code: str
    summary: str
    detail: str


RULES: tuple[Rule, ...] = (
    Rule(
        "LC001",
        "adding a NOT NULL column with no default rewrites or fails",
        "On a table with rows this either fails outright or rewrites every row under "
        "ACCESS EXCLUSIVE. Add the column nullable, backfill in batches, then set it NOT "
        "NULL in a later migration -- or give it a constant server_default, which "
        "Postgres 11 and newer add without touching existing rows.",
    ),
    Rule(
        "LC002",
        "CREATE INDEX without CONCURRENTLY blocks writes for the whole build",
        "The table takes a SHARE lock until the index finishes, so every write waits -- "
        "minutes on a large table, and the queue behind it outlives the migration. Pass "
        "postgresql_concurrently=True and run it outside the transaction (see LC003).",
    ),
    Rule(
        "LC003",
        "CREATE INDEX CONCURRENTLY cannot run inside a transaction",
        "Alembic wraps each migration in one, so this fails at runtime rather than "
        "locking anything -- which is better, but it still means a failed deploy. Wrap "
        "the call: `with op.get_context().autocommit_block():`. Note that a concurrent "
        "build can fail and leave an INVALID index behind, which has to be dropped.",
    ),
    Rule(
        "LC004",
        "SET NOT NULL scans the whole table under ACCESS EXCLUSIVE",
        "Nothing reads or writes the table while it verifies every row. On Postgres 12 "
        "and newer, add a NOT VALID CHECK (col IS NOT NULL) first, VALIDATE it (which "
        "takes only a SHARE UPDATE EXCLUSIVE lock), and then SET NOT NULL -- the scan is "
        "skipped because the constraint already proves it.",
    ),
    Rule(
        "LC005",
        "changing a column type rewrites the entire table",
        "ACCESS EXCLUSIVE for the length of a full rewrite, and the disk needs room for "
        "a second copy. Add a new column, backfill, switch the application over, and drop "
        "the old one. A few of these are free -- varchar(n) to varchar(m) where m is "
        "larger, or to text -- but the rewrite is the default assumption.",
    ),
    Rule(
        "LC006",
        "adding a constraint without NOT VALID scans the table under a lock",
        "A foreign key locks both tables while it checks every existing row. Add it with "
        "NOT VALID, which only checks new rows, then VALIDATE CONSTRAINT separately under "
        "a far weaker lock. Alembic has no keyword for it, so this one is op.execute with "
        "the SQL written out.",
    ),
    Rule(
        "LC007",
        "adding a unique constraint builds its index under a lock",
        "ADD CONSTRAINT UNIQUE builds the backing index the blocking way, whatever else "
        "is going on. Build it yourself first -- CREATE UNIQUE INDEX CONCURRENTLY -- then "
        "ALTER TABLE ... ADD CONSTRAINT ... UNIQUE USING INDEX, which is metadata only.",
    ),
)

BY_CODE: dict[str, Rule] = {rule.code: rule for rule in RULES}
ALL_CODES: frozenset[str] = frozenset(BY_CODE)
