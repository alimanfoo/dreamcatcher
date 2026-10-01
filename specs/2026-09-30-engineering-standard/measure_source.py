"""Measure Dreamcatcher source modules and functions against S1 and S2."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "dreamcatcher"
MODULE_LINE_BAR = 600
FUNCTION_LINE_BAR = 50


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
    return [
        FunctionMeasurement(
            path=path,
            name=node.name,
            line=node.lineno,
            lines=node.end_lineno - node.lineno + 1,
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.end_lineno is not None
        and node.end_lineno - node.lineno + 1 > FUNCTION_LINE_BAR
    ]


def _display_path(*, path: Path) -> str:
    return path.relative_to(SOURCE_ROOT.parent.parent).as_posix()


def _print_modules(*, measurements: list[ModuleMeasurement]) -> None:
    print("## Modules")
    print()
    print("| Module | Lines | S1 |")
    print("| --- | ---: | --- |")
    for measurement in measurements:
        result = "short" if measurement.lines > MODULE_LINE_BAR else "met"
        print(
            f"| `{_display_path(path=measurement.path)}` "
            f"| {measurement.lines} | {result} |"
        )


def _print_functions(*, measurements: list[FunctionMeasurement]) -> None:
    print()
    print("## Functions over the S2 bar")
    print()
    print("| Function | Lines |")
    print("| --- | ---: |")
    for measurement in measurements:
        location = f"{_display_path(path=measurement.path)}:{measurement.line}"
        print(f"| `{location}::{measurement.name}` | {measurement.lines} |")


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
