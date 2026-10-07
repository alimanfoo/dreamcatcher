"""Measure Dreamcatcher source size to guide S1 and S2 review."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "dreamcatcher"
LONGEST_FUNCTIONS_SHOWN = 10


@dataclass(frozen=True)
class ModuleMeasurement:
    """A source module's physical line count."""

    path: Path
    lines: int


@dataclass(frozen=True)
class FunctionMeasurement:
    """A source function's physical line count and location."""

    path: Path
    name: str
    line: int
    lines: int


def _measure_module(*, path: Path) -> ModuleMeasurement:
    source = path.read_text(encoding="utf-8")
    return ModuleMeasurement(path=path, lines=len(source.splitlines()))


def _measure_functions(*, path: Path) -> list[FunctionMeasurement]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    measurements = []
    for node, name in _list_function_definitions(tree=tree):
        if node.end_lineno is None:
            continue
        first_line = min(
            (decorator.lineno for decorator in node.decorator_list),
            default=node.lineno,
        )
        measurements.append(
            FunctionMeasurement(
                path=path,
                name=name,
                line=first_line,
                lines=node.end_lineno - first_line + 1,
            )
        )
    return measurements


def _list_function_definitions(
    *, tree: ast.AST
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    definitions = []

    def visit(*, node: ast.AST, scope: tuple[str, ...]) -> None:
        child_scope = scope
        if isinstance(node, ast.ClassDef):
            child_scope = (*scope, node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            child_scope = (*scope, node.name)
            definitions.append((node, ".".join(child_scope)))
        for child in ast.iter_child_nodes(node):
            visit(node=child, scope=child_scope)

    visit(node=tree, scope=())
    return definitions


def _display_path(*, path: Path) -> str:
    return path.relative_to(SOURCE_ROOT.parent.parent).as_posix()


def _print_modules(*, measurements: list[ModuleMeasurement]) -> None:
    print("## Modules by physical line count")
    print()
    print("| Module | Lines |")
    print("| --- | ---: |")
    for measurement in measurements:
        print(f"| `{_display_path(path=measurement.path)}` | {measurement.lines} |")


def _print_functions(*, measurements: list[FunctionMeasurement]) -> None:
    print()
    print("## Longest functions")
    print()
    print("| Function | Lines |")
    print("| --- | ---: |")
    for measurement in measurements:
        location = f"{_display_path(path=measurement.path)}:{measurement.line}"
        print(f"| `{location}::{measurement.name}` | {measurement.lines} |")


def main() -> None:
    """Print the current source-size measurements as Markdown."""
    paths = sorted(SOURCE_ROOT.rglob("*.py"))
    modules = sorted(
        (_measure_module(path=path) for path in paths),
        key=lambda measurement: (-measurement.lines, measurement.path),
    )
    functions = sorted(
        (
            measurement
            for path in paths
            for measurement in _measure_functions(path=path)
        ),
        key=lambda measurement: (
            -measurement.lines,
            measurement.path,
            measurement.line,
        ),
    )
    print("# Dreamcatcher source measurement")
    print()
    _print_modules(measurements=modules)
    _print_functions(measurements=functions[:LONGEST_FUNCTIONS_SHOWN])


if __name__ == "__main__":
    main()
