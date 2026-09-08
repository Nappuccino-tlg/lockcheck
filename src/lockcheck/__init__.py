"""Find Alembic migrations that will lock a Postgres table, before they run.

Adding an index, tightening a column, or attaching a foreign key are one-line changes that
read as harmless and take a lock that stops every write to the table until they finish. On
a small table nobody notices. On a large one it is an outage, and the first anyone knows
is the deploy that will not finish.

This reads the migration and says which line does it, and what to write instead.
"""

from lockcheck._analyze import Finding, check_file, check_paths, check_source
from lockcheck._rules import RULES, Rule

__all__ = [
    "RULES",
    "Finding",
    "Rule",
    "check_file",
    "check_paths",
    "check_source",
]

__version__ = "0.1.0"
