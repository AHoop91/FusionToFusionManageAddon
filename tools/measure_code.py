"""Measure Python functions against the code-quality guardrails in dev/architecture.md.

Run: uv run python tools/measure_code.py [--json] [paths...]

Reports every function that breaks a guardrail: length over 80 lines,
cyclomatic complexity over 10, nesting deeper than 3, more than 4 parameters.
It also lists unused local variables. The limits are guardrails, not laws:
a function that breaks one needs a written reason, not necessarily a rewrite.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_LINES = 80
MAX_COMPLEXITY = 10
MAX_NESTING = 3
MAX_PARAMETERS = 4

BRANCH_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
    ast.With, ast.AsyncWith, ast.IfExp, ast.Assert, ast.comprehension,
)
NESTING_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith,
)


@dataclass
class FunctionReport:
    path: str
    name: str
    line: int
    lines: int
    complexity: int
    nesting: int
    parameters: int
    unused: list[str]

    def problems(self) -> list[str]:
        found = []
        if self.lines > MAX_LINES:
            found.append(f"{self.lines} lines")
        if self.complexity > MAX_COMPLEXITY:
            found.append(f"complexity {self.complexity}")
        if self.nesting > MAX_NESTING:
            found.append(f"nesting {self.nesting}")
        if self.parameters > MAX_PARAMETERS:
            found.append(f"{self.parameters} parameters")
        if self.unused:
            found.append("unused " + ", ".join(self.unused))
        return found


def _own_nodes(function: ast.AST):
    """Yield the nodes of a function without entering nested functions or classes."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _complexity(function: ast.AST) -> int:
    score = 1
    for node in _own_nodes(function):
        if isinstance(node, BRANCH_NODES):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.match_case):
            score += 1
    return score


def _nesting(node: ast.AST, depth: int = 0) -> int:
    deepest = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        step = 1 if isinstance(child, NESTING_NODES) else 0
        deepest = max(deepest, _nesting(child, depth + step))
    return deepest


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = function.args
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return len([n for n in names if n not in ("self", "cls")])


def _assigned_names(function: ast.AST) -> set[str]:
    return {node.id for node in _own_nodes(function)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}


def _read_names(function: ast.AST) -> set[str]:
    """Names read anywhere in the function, including inside lambdas and nested functions."""
    return {node.id for node in ast.walk(function)
            if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store)}


def _declared_names(function: ast.AST) -> set[str]:
    return {name for node in _own_nodes(function)
            if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names}


def _unused_locals(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    unused = _assigned_names(function) - _read_names(function) - _declared_names(function)
    return sorted(name for name in unused if not name.startswith("_"))


def measure_file(path: Path, root: Path) -> list[FunctionReport]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    reports = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            reports.append(FunctionReport(
                path=path.relative_to(root).as_posix(),
                name=node.name,
                line=node.lineno,
                lines=(node.end_lineno or node.lineno) - node.lineno + 1,
                complexity=_complexity(node),
                nesting=_nesting(node),
                parameters=_parameters(node),
                unused=_unused_locals(node),
            ))
    return reports


def collect(paths: list[Path], root: Path) -> list[FunctionReport]:
    files: list[Path] = []
    for entry in paths:
        files.extend(sorted(entry.rglob("*.py")) if entry.is_dir() else [entry])
    reports = []
    for file in files:
        if "__pycache__" not in file.parts:
            reports.extend(measure_file(file, root))
    return reports


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    targets = [a for a in argv if not a.startswith("--")]
    root = Path(__file__).resolve().parent.parent
    paths = [root / t for t in targets] if targets else [root / "src", root / "tools"]
    reports = collect(paths, root)
    offenders = [r for r in reports if r.problems()]
    if as_json:
        print(json.dumps([asdict(r) | {"problems": r.problems()} for r in offenders], indent=1))
    else:
        for r in sorted(offenders, key=lambda r: (r.path, r.line)):
            print(f"{r.path}:{r.line} {r.name}: {'; '.join(r.problems())}")
        print(f"\n{len(offenders)} of {len(reports)} functions break a guardrail")
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
