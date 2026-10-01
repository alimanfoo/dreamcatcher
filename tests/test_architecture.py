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
PRESENTATION_LIBRARIES = {"flask": "web", "rich": "tui"}
# Status reads the scheduler's records and derivations, which these two
# modules hold, and never the modules that choose or start work.
SCHEDULER_MODULES_STATUS_MAY_IMPORT = {
    f"{PACKAGE}.scheduler.faults",
    f"{PACKAGE}.scheduler.models",
}


def _read_module_name(*, path: Path) -> str:
    return path.relative_to(SOURCE).parts[0].removesuffix(".py")


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
    return [name.split(".")[1] for name in names if name.startswith(f"{PACKAGE}.")]


def _read_import_inventory() -> tuple[
    dict[str, set[str]], dict[str, set[str]], set[str]
]:
    """Read the imports that the architecture rules check.

    Return each module's first-party imports, the modules that import each
    presentation library, and the dotted scheduler modules that status imports.
    """
    names_by_module: dict[str, set[str]] = {}
    for path in SOURCE.rglob("*.py"):
        names = names_by_module.setdefault(_read_module_name(path=path), set())
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names.update(_read_import_names(node=node))
    graph = {
        module: set(_read_imported_modules(names=list(names))) - {module}
        for module, names in names_by_module.items()
    }
    external_importers = {
        library: {
            module
            for module, names in names_by_module.items()
            if any(name.split(".")[0] == library for name in names)
        }
        for library in PRESENTATION_LIBRARIES
    }
    status_scheduler_imports = {
        name
        for name in names_by_module["status"]
        if name.startswith(f"{PACKAGE}.scheduler")
    }
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
    "scheduler": {"daemon", "status"},
    "agent_assignments": SCHEDULING,
    "agent_assignment_pull_requests": SCHEDULING,
    "agent_rounds": SCHEDULING,
    "issue_conversations": SCHEDULING,
    "status": PRESENTATION,
    "feed": PRESENTATION,
    **dict.fromkeys(ADAPTERS, PRESENTATION | SCHEDULING),
    **{module: GRAPH.keys() - STORAGE_REACH for module in STORAGE},
}
# Presentation shows what status and feed derive. It imports no policy module
# and never the other presentation. Direct imports only: both reach the
# scheduler and GitHub through status.
FORBIDDEN_DIRECT_IMPORTS = {
    "tui": {"scheduler", "daemon", "github", "web"},
    "web": {"scheduler", "daemon", "github", "tui"},
}
# Operations and record types a presentation module must not name, because
# status already derives the fact they would be used to rediscover.
DOMAIN_NAMES_PRESENTATION_MUST_NOT_USE = [
    "ErroredAgentRoundEnding",
    "HARNESS_ADAPTERS",
    "InterruptedAgentRoundEnding",
    "find_harness_session_identifier",
    "request_agent_assignment_retry",
]


@pytest.mark.parametrize("module", FORBIDDEN_REACH)
def test_boundary_imports(module):
    assert {module, *FORBIDDEN_REACH[module]} <= GRAPH.keys()
    reached = _find_reached_modules(graph=GRAPH, module=module)

    assert reached & FORBIDDEN_REACH[module] == set()


@pytest.mark.parametrize("module", FORBIDDEN_DIRECT_IMPORTS)
def test_presentation_imports_no_policy_module_and_no_other_presentation(module):
    assert GRAPH[module] & FORBIDDEN_DIRECT_IMPORTS[module] == set()


@pytest.mark.parametrize(("library", "boundary"), PRESENTATION_LIBRARIES.items())
def test_presentation_library_imports_stay_in_their_boundary(library, boundary):
    assert EXTERNAL_IMPORTERS[library] == {boundary}


def test_status_reads_scheduler_records_and_derivations_only():
    assert STATUS_SCHEDULER_IMPORTS <= SCHEDULER_MODULES_STATUS_MAY_IMPORT


@pytest.mark.parametrize("boundary", sorted(PRESENTATION))
@pytest.mark.parametrize("name", DOMAIN_NAMES_PRESENTATION_MUST_NOT_USE)
def test_presentation_does_not_rediscover_what_status_derives(boundary, name):
    for path in (SOURCE / boundary).rglob("*.py"):
        assert name not in path.read_text(encoding="utf-8")
