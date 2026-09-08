"""The command line: what it prints, and what it exits with.

The exit code is the part CI reads, so it gets asserted as carefully as the text.
"""

import pytest

from lockcheck.cli import FOUND, MISUSE, OK, main

LOCKING = """\
import sqlalchemy as sa
from alembic import op


def upgrade():
    op.create_index('ix_users_email', 'users', ['email'])
"""

SAFE = """\
import sqlalchemy as sa
from alembic import op


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix', 'users', ['email'], postgresql_concurrently=True)
"""


@pytest.fixture
def versions(tmp_path):
    directory = tmp_path / "versions"
    directory.mkdir()
    return directory


def test_a_clean_directory_exits_zero(versions, capsys):
    (versions / "0001_safe.py").write_text(SAFE, encoding="utf-8")

    assert main([str(versions)]) == OK
    assert "No locking migrations found." in capsys.readouterr().out


def test_findings_exit_one_so_ci_stops(versions, capsys):
    (versions / "0001_index.py").write_text(LOCKING, encoding="utf-8")

    assert main([str(versions)]) == FOUND

    out = capsys.readouterr().out
    assert "LC002" in out
    assert "1 problem found." in out
    # The fix, not just the complaint.
    assert "postgresql_concurrently" in out


def test_the_count_is_plural_when_it_should_be(versions, capsys):
    (versions / "0001.py").write_text(LOCKING, encoding="utf-8")
    (versions / "0002.py").write_text(LOCKING, encoding="utf-8")

    main([str(versions)])

    assert "2 problems found." in capsys.readouterr().out


def test_a_single_file_can_be_checked(tmp_path, capsys):
    file = tmp_path / "0001_index.py"
    file.write_text(LOCKING, encoding="utf-8")

    assert main([str(file)]) == FOUND


def test_ignoring_a_rule_clears_it(versions, capsys):
    (versions / "0001_index.py").write_text(LOCKING, encoding="utf-8")

    assert main([str(versions), "--ignore", "LC002"]) == OK


def test_ignoring_is_case_insensitive_and_forgiving_of_spaces(versions):
    (versions / "0001_index.py").write_text(LOCKING, encoding="utf-8")

    assert main([str(versions), "--ignore", " lc002 , "]) == OK


def test_an_unknown_rule_code_is_refused(versions, capsys):
    """Silently accepting LC999 would let a typo quietly disable nothing at all."""
    (versions / "0001_index.py").write_text(LOCKING, encoding="utf-8")

    assert main([str(versions), "--ignore", "LC999"]) == MISUSE

    err = capsys.readouterr().err
    assert "LC999" in err
    assert "known codes are" in err


def test_a_missing_path_is_named(tmp_path, capsys):
    assert main([str(tmp_path / "nowhere")]) == MISUSE
    assert "nowhere" in capsys.readouterr().err


def test_a_file_that_is_not_python_is_reported_not_crashed(versions, capsys):
    (versions / "0001_broken.py").write_text("def upgrade(:\n", encoding="utf-8")

    assert main([str(versions)]) == MISUSE
    assert "could not parse" in capsys.readouterr().err


def test_init_files_are_not_migrations(versions, capsys):
    (versions / "__init__.py").write_text(LOCKING, encoding="utf-8")

    assert main([str(versions)]) == OK


def test_listing_the_rules_needs_no_paths(capsys):
    assert main(["--list-rules"]) == OK

    out = capsys.readouterr().out
    assert "LC001" in out
    assert "LC007" in out


def test_findings_are_grouped_by_file(versions, capsys):
    (versions / "0001.py").write_text(LOCKING, encoding="utf-8")
    (versions / "0002.py").write_text(LOCKING, encoding="utf-8")

    main([str(versions)])

    out = capsys.readouterr().out
    assert "0001.py" in out
    assert "0002.py" in out
