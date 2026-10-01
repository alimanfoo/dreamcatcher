import ast
from pathlib import Path

import pytest

PACKAGE = "dreamcatcher"
SOURCE = Path(__file__).parents[1] / "src" / PACKAGE

BOUNDARY_MEMBERS = {
    "agent_assignments": {"agent_assignments", "agent_assignment_pull_requests"},
    "agent_rounds": {"agent_rounds", "agent_round_paths"},
    "scheduler": {"scheduler"},
    "status": {
        "assignment_status",
        "conversation_status",
        "status",
        "status_reader",
        "status_rounds",
    },
    "tui": {"tui", "tui_shared", "tui_status"},
    "web": {"web", "web_feed", "web_models", "web_server", "web_views"},
}
MODULE_BOUNDARY = {
    module: boundary
    for boundary, modules in BOUNDARY_MEMBERS.items()
    for module in modules
}

PRESENTATION = {"tui", "web"}
SCHEDULING = {"scheduler"}
ADAPTERS = ["github", "harness_adapters", "harnesses", "claude", "codex"]
STORAGE = ["state", "documents"]
STORAGE_REACH = {"documents", "errors"}
PRESENTATION_LIBRARIES = {"flask": "web", "rich": "tui"}
STATUS_SCHEDULER_SYMBOLS = {
    "AgentAssignmentObservation",
    "GlobalCooldown",
    "IssueConversationObservation",
    "IssueFact",
    "IssueFactValue",
    "IssueObservation",
    "SchedulerRecord",
    "derive_agent_work_fault",
    "derive_round_purpose",
    "read_scheduler_record",
}


def _read_module_name(*, path: Path) -> str:
    module = path.relative_to(SOURCE).parts[0].removesuffix(".py")
    return MODULE_BOUNDARY.get(module, module)


def _read_import_names(*, node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        source = node.module or ""
        return (
            [f"{PACKAGE}.{alias.name}" for alias in node.names]
            if source == PACKAGE
            else [source]
        )
    return []


def _read_imported_modules(*, names: list[str]) -> list[str]:
    modules = [name.split(".")[1] for name in names if name.startswith(f"{PACKAGE}.")]
    return [MODULE_BOUNDARY.get(module, module) for module in modules]


def _read_status_scheduler_symbols(
    *, module: str, node: ast.AST, names: list[str]
) -> set[str]:
    if module != "status":
        return set()
    if isinstance(node, ast.ImportFrom) and node.module == f"{PACKAGE}.scheduler":
        return {alias.name for alias in node.names}
    if any(name.startswith(f"{PACKAGE}.scheduler") for name in names):
        return {"*"}
    return set()


def _read_import_inventory() -> tuple[
    dict[str, set[str]], dict[str, set[str]], set[str]
]:
    """Read the first-party, presentation-library and status-scheduler imports."""
    graph: dict[str, set[str]] = {}
    external_importers = {library: set() for library in PRESENTATION_LIBRARIES}
    status_scheduler_imports = set()
    for path in SOURCE.rglob("*.py"):
        module = _read_module_name(path=path)
        imported = graph.setdefault(module, set())
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = _read_import_names(node=node)
            imported.update(_read_imported_modules(names=names))
            for library in external_importers:
                if any(name.split(".")[0] == library for name in names):
                    external_importers[library].add(module)
            status_scheduler_imports.update(
                _read_status_scheduler_symbols(
                    module=module,
                    node=node,
                    names=names,
                )
            )
        imported.discard(module)
    return graph, external_importers, status_scheduler_imports


def _find_reached_modules(*, graph: dict[str, set[str]], module: str) -> set[str]:
    reached = set()
    waiting = [module]
    while waiting:
        for imported in graph[waiting.pop()] - reached:
            reached.add(imported)
            waiting.append(imported)
    return reached


GRAPH, EXTERNAL_IMPORTERS, STATUS_SCHEDULER_IMPORTS = _read_import_inventory()

# Each architecture boundary beside the boundaries it must never reach through
# its imports, directly or not.
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
FORBIDDEN_DIRECT_IMPORTS = {
    "tui": {"scheduler"},
    "web": {"scheduler"},
}


@pytest.mark.parametrize("module", FORBIDDEN_REACH)
def test_boundary_imports(module):
    assert {module, *FORBIDDEN_REACH[module]} <= GRAPH.keys()
    reached = _find_reached_modules(graph=GRAPH, module=module)

    assert reached & FORBIDDEN_REACH[module] == set()


@pytest.mark.parametrize("module", FORBIDDEN_DIRECT_IMPORTS)
def test_presentation_imports_status_instead_of_scheduler(module):
    assert GRAPH[module] & FORBIDDEN_DIRECT_IMPORTS[module] == set()


@pytest.mark.parametrize(("library", "boundary"), PRESENTATION_LIBRARIES.items())
def test_presentation_library_imports_stay_in_their_boundary(library, boundary):
    assert EXTERNAL_IMPORTERS[library] == {boundary}


def test_status_imports_only_pure_scheduler_symbols():
    assert STATUS_SCHEDULER_IMPORTS <= STATUS_SCHEDULER_SYMBOLS
