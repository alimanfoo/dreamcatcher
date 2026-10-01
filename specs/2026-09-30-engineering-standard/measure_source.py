"""Measure Dreamcatcher source modules and functions against S1 and S2."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "dreamcatcher"
MODULE_LINE_BAR = 600
FUNCTION_LINE_BAR = 50

# These modules and functions hold one architecture-level transaction or
# boundary. Splitting them would hide that shape rather than reveal a concept.
MODULE_EXCEPTIONS = {
    "github.py": "the single GitHub command and response boundary",
}
FUNCTION_EXCEPTIONS = {
    (
        "agent_assignments.py",
        "AgentAssignmentCreator.create",
    ): "the assignment creation transaction",
    (
        "agent_rounds.py",
        "AgentRound.__init__",
    ): "the round process and thread assembly",
    ("cli.py", "build_cli_parser"): "the complete command-line grammar",
    ("daemon.py", "DreamcatcherDaemon.run"): "the daemon lifecycle",
    (
        "daemon.py",
        "DreamcatcherDaemon.run_scheduler_cycle",
    ): "one isolated scheduler cycle",
    (
        "scheduler/coordinator.py",
        "AgentWorkScheduler.tick",
    ): "one scheduler tick transaction",
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
    print("## Modules")
    print()
    print("| Module | Lines | S1 |")
    print("| --- | ---: | --- |")
    for measurement in measurements:
        module = measurement.path.relative_to(SOURCE_ROOT).as_posix()
        exception = MODULE_EXCEPTIONS.get(module)
        if measurement.lines <= MODULE_LINE_BAR:
            result = "met"
        elif exception is None:
            result = "short"
        else:
            result = f"exception: {exception}"
        print(
            f"| `{_display_path(path=measurement.path)}` "
            f"| {measurement.lines} | {result} |"
        )


def _print_functions(*, measurements: list[FunctionMeasurement]) -> None:
    print()
    print("## Functions over the S2 bar")
    print()
    print("| Function | Lines | Named exception |")
    print("| --- | ---: | --- |")
    for measurement in measurements:
        location = f"{_display_path(path=measurement.path)}:{measurement.line}"
        module = measurement.path.relative_to(SOURCE_ROOT).as_posix()
        exception = FUNCTION_EXCEPTIONS.get((module, measurement.name), "")
        print(
            f"| `{location}::{measurement.name}` | {measurement.lines} | {exception} |"
        )


def main() -> None:
    """Print the current S1 and S2 source measurements as Markdown."""
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
