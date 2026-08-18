"""Every way out of this process is a door the profile rules on (`D-178`).

`ADR-0006` §30 argues that the network policy *"cannot be bolted on after the
providers multiply"*. `D-172` gated the five that exist; this is the check that
the sixth cannot arrive ungated. It fails in two directions:

* a module imports a network-capable library and is not registered as a door;
* a door is registered against an environment variable that no
  ``runtime_profile.require`` in ``src`` actually refuses on.

The second half is the one that matters most. A registry of doors that nobody
checks against the refusals is a docstring, and this estate has been caught
before by a sentence asserting a gate that no branch enforced (`D-32`).

**The database is not a door.** ``create_engine`` reaches another machine as
readily as any provider, but it is this service's own store rather than a thing
the deployment chooses to reach: refusing it is refusing to boot, the same
argument that left ``MEMORY_BASE_URL`` out of `D-177`. It is excluded by name,
below, rather than by the scan failing to notice it.

**The limit, stated rather than hidden:** the scan knows the libraries the
estate has. A provider on an SDK nobody has imported yet would not match — so
:class:`TestEveryDependencyIsClassified` requires every declared dependency to
be placed in one of the three kinds, because a new SDK is a new dependency line
before it is a new import. A vendored client with no dependency line still
escapes both.
"""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "kae_memory"
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

EGRESS = "egress"
"""Reaches something outside this deployment's control. Needs a profile check."""

STORE = "store"
"""This service's own persistence. Refusing it is refusing to boot."""

INBOUND = "inbound"
"""Serves callers. Nothing leaves on it."""

CLASSIFIED: Mapping[str, str] = {
    "alembic": STORE,
    "anthropic": EGRESS,
    "boto3": EGRESS,
    "fastapi": INBOUND,
    "httpx": EGRESS,
    "mcp": INBOUND,
    "psycopg": STORE,
    "sqlalchemy": STORE,
    "sqlalchemy-cockroachdb": STORE,
    "uvicorn": INBOUND,
}

EGRESS_IMPORTS = frozenset({"anthropic", "boto3", "httpx"}) | frozenset(
    {"aiohttp", "ftplib", "openai", "requests", "smtplib", "socket", "urllib.request", "websockets"}
)
"""What the estate imports today, plus the ways it plausibly would tomorrow."""

DOORS: Mapping[str, str] = {
    "agents/bedrock.py": "KAE_EXTRACTION",
    "agents/goal_judge.py": "KAE_GOAL_JUDGE",
    "agents/ollama.py": "KAE_EMBEDDING",
    "agents/ollama_classifier.py": "KAE_OBSERVATION_CLASSIFIER",
    "agents/ollama_extraction.py": "KAE_EXTRACTION",
    "agents/ollama_review.py": "KAE_REVIEW",
    "agents/semantic_classifier.py": "KAE_OBSERVATION_CLASSIFIER",
    "agents/titan.py": "KAE_EMBEDDING",
}
"""Module → the variable whose value a profile check refuses.

``agents/bedrock.py`` holds both the extraction and the review adapter and is
listed once, under the variable it was written for; ``KAE_REVIEW`` is refused in
``worker/execution.py`` beside it and is covered by that module's own entry in
the refusals below.
"""


NOT_DOORS: Mapping[str, str] = {
    "agents/provider.py": (
        "boto3.Session().region_name reads the local AWS configuration. It builds no "
        "client and opens no socket; the clients it selects are doors in their own "
        "modules, and this is where five of them are refused."
    ),
    "worker/__main__.py": (
        "socket.gethostname() names this process for the worker identifier. Nothing is sent."
    ),
}
"""Imports a network-capable library and reaches nothing. Each says why.

Deliberately a registry with reasons rather than a cleverer scan. Deciding
whether an import is a reach is a judgement, and a heuristic that made it
silently would be the thing this file exists to refuse.
"""


def _modules() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(SRC.rglob("*.py")):
        yield path.relative_to(SRC).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def _imported_names(tree: ast.Module) -> set[str]:
    """Every module name imported anywhere, including inside a function body.

    Provider SDKs here are imported lazily inside constructors, so a scan that
    only read module-level imports would report the two Bedrock doors as absent.
    """

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def _reaches_out(tree: ast.Module) -> bool:
    imported = _imported_names(tree)
    return any(
        name == library or name.startswith(f"{library}.")
        for name in imported
        for library in EGRESS_IMPORTS
    )


def _refused_variables() -> set[str]:
    """The variables some ``runtime_profile.require`` in ``src`` actually refuses on."""

    refused: set[str] = set()
    for _, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute) or function.attr != "require":
                continue
            for keyword in node.keywords:
                if keyword.arg == "variable" and isinstance(keyword.value, ast.Constant):
                    refused.add(str(keyword.value.value))
    return refused


class TestEveryDoorIsRegistered:
    def test_no_module_reaches_out_without_being_a_door(self) -> None:
        known = set(DOORS) | set(NOT_DOORS)
        unregistered = sorted(
            module for module, tree in _modules() if _reaches_out(tree) and module not in known
        )
        assert not unregistered, (
            "these modules import a network-capable library and are not registered "
            "egress doors:\n  "
            + "\n  ".join(unregistered)
            + "\nGive the call a runtime_profile.require and add it to DOORS, or say "
            "here why it is not a reach the profile rules on."
        )

    def test_no_door_is_registered_that_stopped_reaching_out(self) -> None:
        """A stale registry entry reads exactly like a gated door."""

        trees = dict(_modules())
        stale = sorted(
            module
            for module in (*DOORS, *NOT_DOORS)
            if module not in trees or not _reaches_out(trees[module])
        )
        assert not stale, "registered here and no longer importing anything outbound: " + ", ".join(
            stale
        )


class TestEveryDoorIsRefusedSomewhere:
    def test_each_door_names_a_variable_a_profile_check_refuses_on(self) -> None:
        refused = _refused_variables()
        ungated = sorted({variable for variable in DOORS.values() if variable not in refused})
        assert not ungated, (
            "these doors are registered against variables that no "
            "runtime_profile.require in src refuses on: " + ", ".join(ungated)
        )

    def test_the_five_provider_variables_are_all_refused(self) -> None:
        """`D-172` wired five choice points. Losing one would be silent."""

        assert _refused_variables() >= {
            "KAE_EMBEDDING",
            "KAE_EXTRACTION",
            "KAE_GOAL_JUDGE",
            "KAE_OBSERVATION_CLASSIFIER",
            "KAE_REVIEW",
        }


class TestEveryDependencyIsClassified:
    def test_a_new_dependency_must_be_placed_before_it_can_be_imported(self) -> None:
        project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
        declared = list(project["dependencies"])
        for name, group in project.get("optional-dependencies", {}).items():
            if name != "dev":
                declared.extend(group)

        unclassified = sorted(
            {_distribution(requirement) for requirement in declared} - set(CLASSIFIED)
        )
        assert not unclassified, (
            "declared dependencies with no egress classification: "
            + ", ".join(unclassified)
            + "\nAdd each to CLASSIFIED. A dependency that reaches out is a door."
        )

    def test_every_egress_distribution_is_scanned_for(self) -> None:
        egress = {name for name, kind in CLASSIFIED.items() if kind == EGRESS}
        assert egress <= EGRESS_IMPORTS, "classified as egress and not scanned for: " + ", ".join(
            sorted(egress - EGRESS_IMPORTS)
        )


def _distribution(requirement: str) -> str:
    for separator in (">=", "==", "<", ">", "[", ";", "~="):
        requirement = requirement.split(separator)[0]
    return requirement.strip().lower()
