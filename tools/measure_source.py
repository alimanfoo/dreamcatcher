"""Measure Dreamcatcher source size to guide S1 and S2 review."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "dreamcatcher"
FUNCTION_LINE_BAR = 50

# The functions that stay whole over the bar, each with its reason. Each is one
# transaction whose steps the architecture or the ontology lists in order, and
# splitting it would hide that order rather than name a concept.
FUNCTIONS_THAT_STAY_WHOLE = {
    "build_cli_parser": "the complete command-line grammar, in one place",
    "DreamcatcherDaemon.run": "the daemon lifecycle, as the architecture lists it",
    "AgentWorkScheduler.tick": "the scheduler tick, as the architecture lists it",
    "AgentAssignmentCreator.create": ("assignment creation, as the ontology lists it"),
    "AgentRound.__init__": (
        "starting a round as one transaction: inputs, process, record, readers"
    ),
}


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
        lines = node.end_lineno - first_line + 1
        if lines > FUNCTION_LINE_BAR:
            measurements.append(
                FunctionMeasurement(
                    path=path,
                    name=name,
                    line=first_line,
                    lines=lines,
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
    print("## Functions over the S2 bar")
    print()
    print("| Function | Lines | Stays whole because |")
    print("| --- | ---: | --- |")
    for measurement in measurements:
        location = f"{_display_path(path=measurement.path)}:{measurement.line}"
        reason = FUNCTIONS_THAT_STAY_WHOLE.get(measurement.name, "")
        print(f"| `{location}::{measurement.name}` | {measurement.lines} | {reason} |")


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
    _print_functions(measurements=functions)


if __name__ == "__main__":
    main()
