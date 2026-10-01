import ast
from pathlib import Path

import pytest

PACKAGE = "dreamcatcher"
SOURCE = Path(__file__).parents[1] / "src" / PACKAGE

PRESENTATION = {"tui", "web"}
SCHEDULING = {"scheduler"}
ADAPTERS = ["github", "harness_adapters", "harnesses", "claude", "codex"]
STORAGE = ["state", "documents"]
STORAGE_REACH = {"documents", "errors"}


def read_import_graph():
    """Map each top-level module, or package, to the modules it imports."""
    graph = {}
    for path in SOURCE.rglob("*.py"):
        module = path.relative_to(SOURCE).parts[0].removesuffix(".py")
        imported = graph.setdefault(module, set())
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imported.update(read_imported_modules(node=node))
        imported.discard(module)
    return graph


def read_imported_modules(*, node):
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        source = node.module or ""
        names = (
            [f"{PACKAGE}.{alias.name}" for alias in node.names]
            if source == PACKAGE
            else [source]
        )
    else:
        return []
    return [name.split(".")[1] for name in names if name.startswith(f"{PACKAGE}.")]


def find_reached_modules(*, graph, module):
    reached = set()
    waiting = [module]
    while waiting:
        for imported in graph[waiting.pop()] - reached:
            reached.add(imported)
            waiting.append(imported)
    return reached


GRAPH = read_import_graph()

# Each module the architecture's dependency direction names, beside the modules
# it must never reach through its imports, directly or not.
FORBIDDEN_REACH = {
    "scheduler": {"daemon"},
    "agent_assignments": SCHEDULING,
    "agent_rounds": SCHEDULING,
    "issue_conversations": SCHEDULING,
    "status": PRESENTATION,
    "feed": PRESENTATION,
    **dict.fromkeys(ADAPTERS, PRESENTATION | SCHEDULING),
    **{module: GRAPH.keys() - STORAGE_REACH for module in STORAGE},
}


@pytest.mark.parametrize("module", FORBIDDEN_REACH)
def test_no_module_reaches_a_module_the_architecture_keeps_it_from(module):
    assert {module, *FORBIDDEN_REACH[module]} <= GRAPH.keys()
    reached = find_reached_modules(graph=GRAPH, module=module)

    assert reached & FORBIDDEN_REACH[module] == set()
