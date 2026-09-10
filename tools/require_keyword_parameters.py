"""Report every parameter that a caller could pass by position.

Passing by name is what makes a call say what each argument means, and it is
what keeps a reordered signature from quietly changing what every caller
passes. So each parameter in this project is keyword-only, and a parameter that
something outside this project passes by position is declared positional-only,
which says so where a reader meets it.

A test, a fixture and a pytest_ hook are left alone. pytest is what calls each
of those, and it resolves every argument by the parameter's own name.

This reads a def statement and nothing else. A lambda has no keyword-only form,
so write a def for any callback that takes more than one argument, and the check
then covers it.
"""

import ast
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

# What a method's receiver is called. It arrives by position, whatever the
# parameters after it do.
RECEIVERS = ("self", "cls")


def is_called_by_pytest(*, definition: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether pytest is what calls this definition, so its shape is pytest's."""
    if definition.name.startswith(("test_", "pytest_")):
        return True
    return any(
        "fixture" in ast.unparse(decorator) for decorator in definition.decorator_list
    )


def positional_parameters(*, text: str) -> Iterator[str]:
    """Yield the line and the words naming each such parameter."""
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if is_called_by_pytest(definition=node):
            continue
        taken = [argument.arg for argument in node.args.args]
        if taken and taken[0] in RECEIVERS:
            taken = taken[1:]
        if node.args.vararg is not None:
            taken.append(f"*{node.args.vararg.arg}")
        for parameter in taken:
            yield f"{node.lineno} {node.name} takes {parameter} by position"


def main(*, paths: Sequence[str]) -> int:
    """Name every parameter a caller could pass by position, and fail if any."""
    found = False
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        for reported in positional_parameters(text=text):
            print(f"{path}:{reported}")
            found = True
    return int(found)


if __name__ == "__main__":
    sys.exit(main(paths=sys.argv[1:]))
