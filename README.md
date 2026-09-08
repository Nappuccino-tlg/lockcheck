# lockcheck

Finds Alembic migrations that will lock a Postgres table, before they run.

[![CI](https://github.com/Nappuccino-tlg/lockcheck/actions/workflows/ci.yml/badge.svg)](https://github.com/Nappuccino-tlg/lockcheck/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20--%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
[![PyPI](https://img.shields.io/pypi/v/lockcheck)](https://pypi.org/project/lockcheck/)

```bash
pip install lockcheck
lockcheck
```

## The line that takes the site down

```python
op.create_index("ix_clicks_clicked_at", "clicks", ["clicked_at"])
```

One line, no obvious cost, reviewed and approved. On the developer's machine the table has
forty rows and it finishes instantly. In production it has forty million, Postgres holds a
lock that blocks every write to `clicks` until the index is built, and everything writing
to that table stops — for as long as it takes.

Nobody finds out at review time. They find out during the deploy.

```
alembic/versions/0002_click_rollups.py
    47  LC002  CREATE INDEX without CONCURRENTLY blocks writes for the whole build
            The table takes a SHARE lock until the index finishes, so every write waits
            -- minutes on a large table, and the queue behind it outlives the migration.
            Pass postgresql_concurrently=True and run it outside the transaction (see
            LC003).

1 problem found.
```

Exit code 1, so CI stops. Every finding names the fix, because a linter that reports a
problem and leaves the answer as an exercise gets silenced by the first person in a hurry.

## The rules

| | |
|---|---|
| **LC001** | adding a `NOT NULL` column with no default rewrites the table, or fails |
| **LC002** | `CREATE INDEX` without `CONCURRENTLY` blocks writes for the whole build |
| **LC003** | `CREATE INDEX CONCURRENTLY` inside a transaction, which cannot work |
| **LC004** | `SET NOT NULL` scans the whole table under `ACCESS EXCLUSIVE` |
| **LC005** | changing a column type rewrites the entire table |
| **LC006** | a foreign key or check constraint added without `NOT VALID` |
| **LC007** | a unique constraint, which builds its index the blocking way |

`lockcheck --list-rules` prints them; each finding prints the full explanation.

## What it does not report

This matters more than the list above. A linter is judged on its false positives, and the
first thing this one did against a real project was produce ten findings that were all
noise — indexes on tables created three lines earlier, empty and invisible to anything
else.

So a table created or dropped in the same migration is not locked, and operations on it
are not reported. `create_table` is never flagged for the same reason: a table nothing has
touched yet has nothing to block.

A table named by anything other than a literal string gets the cautious answer and is
treated as pre-existing. Reporting something harmless costs a moment; staying quiet about
a real lock costs an outage.

## What it cannot see

**Raw SQL.** `op.execute("CREATE INDEX ...")` is a string as far as Python is concerned.
Half-parsing SQL by hand would be a worse lie than not parsing it, so this says so instead.

**Deploy ordering.** `drop_column` and `rename_table` take no meaningful lock and will
still break the application running against the old schema. That is a real problem and a
different one, about the order of deploys rather than the shape of a migration.

**Your data.** Every rule here is about what Postgres *would* do to a large table. On a
table with a hundred rows, all of them are noise — which is what `--ignore` and the
`# lockcheck: ignore` comment are for.

## Silencing

```python
op.create_index("ix", "settings", ["key"])  # lockcheck: ignore[LC002]
```

Bare `# lockcheck: ignore` silences the line; the bracketed form names rules. The comment
counts anywhere in a multi-line call, which is where anyone would write it — beside the
argument that made it safe.

Across a whole project, `--ignore LC002,LC004`.

## In CI

```yaml
- run: pip install lockcheck
- run: lockcheck
```

With no arguments it checks `alembic/versions`. Give it paths for anywhere else.

## How it reads a migration

The file is parsed, not searched. A regular expression finds `op.create_index(` and then
has no idea whether the call three lines down passed `postgresql_concurrently=True`,
whether it sits inside an autocommit block, or whether the whole thing is inside a
docstring. Each of those changes the answer, and the calls this exists to catch are
exactly the ones long enough to wrap across lines.

Nothing is imported or executed. Reading a migration should not be able to run one.

## Requirements

Python 3.10 or newer. **No dependencies** — `ast` and `argparse` from the standard
library. A linter that drags a dependency tree into someone's CI is one more thing for
them to resolve, pin and upgrade, and this needs none of it.

Alembic itself is not required. It is not imported.

## Tests

```bash
pytest
```

No database, no services, no fixtures to stand up. It is a static analyser, so the whole
suite runs in about a tenth of a second.

## License

MIT
