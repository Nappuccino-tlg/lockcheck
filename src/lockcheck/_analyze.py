"""Reading a migration to find out what it will lock.

The file is parsed, not searched. A regular expression over the text finds
`op.create_index(` and then has no idea whether the call three lines down passed
`postgresql_concurrently=True`, whether it sits inside an autocommit block, or whether the
whole thing is inside a string. Every one of those changes the answer, and the ones this
tool exists to catch are exactly the calls long enough to wrap across lines.

What it deliberately cannot see is `op.execute("...")`. The SQL inside is a string to
Python and staying out of the business of parsing it by hand is a smaller lie than
half-parsing it -- the README says so rather than letting anyone assume otherwise.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from lockcheck._rules import ALL_CODES, BY_CODE

# `# lockcheck: ignore` silences everything on the line; `# lockcheck: ignore[LC002]`
# silences one rule. Anywhere in the call's lines counts, because the natural place to
# write it is beside the argument that made the call safe.
IGNORE = re.compile(r"#\s*lockcheck:\s*ignore(?:\[([A-Z0-9,\s]+)\])?")


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str

    @property
    def summary(self) -> str:
        return BY_CODE[self.code].summary

    @property
    def detail(self) -> str:
        return BY_CODE[self.code].detail


def _op_call(node: ast.Call) -> str | None:
    """The Alembic operation this call is, or None if it is not one.

    Matches `op.create_index(...)` and `alembic.op.create_index(...)`, which are the two
    ways migrations are actually written.
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    value = func.value
    if isinstance(value, ast.Name) and value.id == "op":
        return func.attr
    if isinstance(value, ast.Attribute) and value.attr == "op":
        return func.attr
    return None


# Which argument names the table an operation locks, by keyword and by position. A
# foreign key names two and locks both, so it lists both.
TABLES_OF: dict[str, tuple[tuple[str, int], ...]] = {
    "add_column": (("table_name", 0),),
    "alter_column": (("table_name", 0),),
    "create_index": (("table_name", 1),),
    "drop_index": (("table_name", 1),),
    "create_foreign_key": (("source_table", 1), ("referent_table", 2)),
    "create_check_constraint": (("table_name", 1),),
    "create_unique_constraint": (("table_name", 1),),
}


def _argument(node: ast.Call, name: str, position: int) -> ast.expr | None:
    keyword = _keyword(node, name)
    if keyword is not None:
        return keyword.value
    if position < len(node.args):
        return node.args[position]
    return None


def _literal_table(expr: ast.expr | None) -> str | None:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def _keyword(node: ast.Call, name: str) -> ast.keyword | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword
    return None


def _is_true(keyword: ast.keyword | None) -> bool:
    return (
        keyword is not None
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
    )


def _is_false(keyword: ast.keyword | None) -> bool:
    return (
        keyword is not None
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
    )


def _column_calls(node: ast.Call) -> list[ast.Call]:
    """The sa.Column(...) calls inside an add_column, wherever they were written."""
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == "Column"
    ]


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[tuple[int, int, str]] = []
        # Depth rather than a flag: nested with-blocks are legal and one of them being an
        # autocommit block still means the call is outside a transaction.
        self._autocommit = 0
        self._fresh: set[str] = set()

    # -- context -------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """A migration function is the scope in which a table counts as new.

        An index on a table created three lines earlier locks nothing: the table has no
        rows and nobody is reading it. Reporting it anyway was this tool's own first
        result against a real project -- ten findings, all of them noise -- and a linter
        gets read exactly as long as it is worth reading.

        Tables dropped in the same function are treated the same way, since an index on
        something about to disappear is not worth a lock either.
        """
        previous = self._fresh
        self._fresh = previous | _tables_touched(node)
        self.generic_visit(node)
        self._fresh = previous

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def _on_a_fresh_table(self, operation: str, node: ast.Call) -> bool:
        """True when every table this call touches was created or dropped right here.

        A table named by anything other than a literal -- a variable, a format string --
        cannot be checked, so it is treated as pre-existing. Reporting something harmless
        costs a moment; staying quiet about a real lock costs an outage.
        """
        wanted = TABLES_OF.get(operation)
        if not wanted:
            return False
        names = [_literal_table(_argument(node, name, position)) for name, position in wanted]
        return bool(names) and all(name in self._fresh for name in names)

    def visit_With(self, node: ast.With) -> None:
        if any(_opens_autocommit(item.context_expr) for item in node.items):
            self._autocommit += 1
            self.generic_visit(node)
            self._autocommit -= 1
        else:
            self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)  # type: ignore[arg-type]

    # -- rules ---------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        operation = _op_call(node)
        if operation is not None and not self._on_a_fresh_table(operation, node):
            getattr(self, f"_check_{operation}", self._nothing)(node)
        self.generic_visit(node)

    def _nothing(self, node: ast.Call) -> None:
        """Most operations take no interesting lock. Saying so is the default."""

    def _report(self, node: ast.Call, code: str) -> None:
        self.findings.append((node.lineno, node.end_lineno or node.lineno, code))

    def _check_add_column(self, node: ast.Call) -> None:
        for column in _column_calls(node):
            not_null = _is_false(_keyword(column, "nullable"))
            has_default = _keyword(column, "server_default") is not None
            if not_null and not has_default:
                self._report(node, "LC001")

    def _check_create_index(self, node: ast.Call) -> None:
        concurrent = _is_true(_keyword(node, "postgresql_concurrently"))
        if not concurrent:
            self._report(node, "LC002")
        elif not self._autocommit:
            self._report(node, "LC003")

    def _check_drop_index(self, node: ast.Call) -> None:
        # Dropping takes the same lock as building, and is just as easy to do concurrently.
        self._check_create_index(node)

    def _check_alter_column(self, node: ast.Call) -> None:
        if _is_false(_keyword(node, "nullable")):
            self._report(node, "LC004")
        if _keyword(node, "type_") is not None:
            self._report(node, "LC005")

    def _check_create_foreign_key(self, node: ast.Call) -> None:
        self._report(node, "LC006")

    def _check_create_check_constraint(self, node: ast.Call) -> None:
        self._report(node, "LC006")

    def _check_create_unique_constraint(self, node: ast.Call) -> None:
        self._report(node, "LC007")


def _tables_touched(node: ast.AST) -> set[str]:
    """Tables created or dropped anywhere inside this function."""
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        operation = _op_call(child)
        if operation in {"create_table", "drop_table"}:
            name = _literal_table(_argument(child, "table_name", 0))
            if name is not None:
                names.add(name)
    return names


def _opens_autocommit(expr: ast.expr) -> bool:
    """True for `op.get_context().autocommit_block()` and anything ending the same way."""
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "autocommit_block"
    )


def _ignored(source_lines: list[str], start: int, end: int) -> set[str] | None:
    """Codes silenced across a call's lines, or None where nothing is silenced.

    An empty set means "everything here", which is what a bare `# lockcheck: ignore` says.
    """
    silenced: set[str] = set()
    found = False
    for number in range(start, end + 1):
        if number > len(source_lines):
            break
        match = IGNORE.search(source_lines[number - 1])
        if not match:
            continue
        found = True
        codes = match.group(1)
        if codes is None:
            return set()
        silenced.update(code.strip() for code in codes.split(",") if code.strip())
    return silenced if found else None


def check_source(source: str, path: Path) -> list[Finding]:
    """Findings for one migration's source. Raises SyntaxError on a file that is not Python."""
    tree = ast.parse(source, filename=str(path))
    visitor = _Visitor(path)
    visitor.visit(tree)

    lines = source.splitlines()
    findings = []
    for start, end, code in visitor.findings:
        silenced = _ignored(lines, start, end)
        if silenced is not None and (not silenced or code in silenced):
            continue
        findings.append(Finding(path=path, line=start, code=code))
    return sorted(findings, key=lambda f: (f.line, f.code))


def check_file(path: Path) -> list[Finding]:
    return check_source(path.read_text(encoding="utf-8"), path)


def collect(paths: list[Path]) -> list[Path]:
    """Every migration under the given paths, in a stable order.

    Directories are walked for *.py; __init__.py and dotfiles are skipped because a
    versions directory sometimes has them and they are never migrations.
    """
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                child
                for child in sorted(path.rglob("*.py"))
                if child.name != "__init__.py" and not child.name.startswith(".")
            )
        elif path.suffix == ".py":
            files.append(path)
    return files


def check_paths(paths: list[Path], ignore: frozenset[str] = frozenset()) -> list[Finding]:
    unknown = ignore - ALL_CODES
    if unknown:
        raise ValueError(f"unknown rule code(s): {', '.join(sorted(unknown))}")

    findings = []
    for file in collect(paths):
        findings.extend(f for f in check_file(file) if f.code not in ignore)
    return findings
