"""The command line, and what it prints.

Output is one finding per block: where it is, what will happen, and what to do instead.
The last part is the one that matters -- a linter that reports a problem and leaves the
fix as an exercise gets added to the ignore list on the day someone is in a hurry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lockcheck._analyze import Finding, check_paths
from lockcheck._rules import ALL_CODES, RULES

# Where Alembic keeps them, so the common case is `lockcheck` with no arguments.
DEFAULT_PATH = Path("alembic/versions")

OK = 0
FOUND = 1
MISUSE = 2


def _wrap(text: str, width: int, indent: str) -> str:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    return "\n".join(indent + line for line in lines)


def render(findings: list[Finding], width: int = 88) -> str:
    if not findings:
        return "No locking migrations found."

    out: list[str] = []
    current_file = None
    for finding in findings:
        if finding.path != current_file:
            if current_file is not None:
                out.append("")
            out.append(str(finding.path))
            current_file = finding.path
        out.append(f"  {finding.line:>4}  {finding.code}  {finding.summary}")
        out.append(_wrap(finding.detail, width - 12, " " * 12))
        out.append("")

    total = len(findings)
    out.append(f"{total} problem{'s' if total != 1 else ''} found.")
    return "\n".join(out)


def _list_rules() -> str:
    return "\n".join(f"{rule.code}  {rule.summary}" for rule in RULES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lockcheck",
        description="Find Alembic migrations that will lock a Postgres table.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=f"migration files or directories (default: {DEFAULT_PATH})",
    )
    parser.add_argument(
        "--ignore",
        default="",
        metavar="CODES",
        help="comma-separated rule codes to skip, e.g. --ignore LC002,LC004",
    )
    parser.add_argument(
        "--list-rules", action="store_true", help="print every rule and what it catches"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_rules:
        print(_list_rules())
        return OK

    paths = args.paths or [DEFAULT_PATH]
    missing = [p for p in paths if not p.exists()]
    if missing:
        # Named rather than counted: "no such path" with nothing after it sends people
        # looking at the wrong argument.
        print(f"lockcheck: no such path: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return MISUSE

    ignore = frozenset(code.strip().upper() for code in args.ignore.split(",") if code.strip())
    try:
        findings = check_paths(paths, ignore=ignore)
    except ValueError as exc:
        print(f"lockcheck: {exc}", file=sys.stderr)
        print(f"lockcheck: known codes are {', '.join(sorted(ALL_CODES))}", file=sys.stderr)
        return MISUSE
    except SyntaxError as exc:
        print(f"lockcheck: could not parse {exc.filename}: {exc.msg}", file=sys.stderr)
        return MISUSE

    print(render(findings))
    return FOUND if findings else OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
