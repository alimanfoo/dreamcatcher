"""Report every parameter that a caller could pass by position.

Passing by name is what makes a call say what each argument means, and it is
what keeps a reordered signature from quietly changing what every caller
passes. So each parameter in this project is keyword-only, and a parameter that
something outside this project passes by position is declared positional-only,
which says so where a reader meets it.

A test, a fixture and a pytest_ hook are left alone. pytest is what calls each
of those, and it resolves every argument by the parameter's own name.
"""

import ast
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

# What a method's receiver is called. It arrives by position, whatever the
# parameters after it do.
RECEIVERS = ("self", "cls")


def is_pytests(*, definition: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether pytest is what calls this definition, so its shape is pytest's."""
    if definition.name.startswith(("test_", "pytest_")):
        return True
    return any(
        "fixture" in ast.unparse(decorator) for decorator in definition.decorator_list
    )


def positional_parameters(*, text: str) -> Iterator[tuple[int, str, str]]:
    """Yield the line, the definition and the name of each such parameter."""
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if is_pytests(definition=node):
            continue
        taken = [argument.arg for argument in node.args.args]
        if taken and taken[0] in RECEIVERS:
            taken = taken[1:]
        for name in taken:
            yield node.lineno, node.name, name
        if node.args.vararg is not None:
            yield node.lineno, node.name, f"*{node.args.vararg.arg}"


def main(*, paths: Sequence[str]) -> int:
    """Name every parameter a caller could pass by position, and fail if any."""
    found = False
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        for number, definition, name in positional_parameters(text=text):
            print(f"{path}:{number} {definition} takes {name} by position")
            found = True
    return int(found)


if __name__ == "__main__":
    sys.exit(main(paths=sys.argv[1:]))
