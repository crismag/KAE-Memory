"""`KAE_OLLAMA_URL` says where Ollama is, at every door that talks to it (`D-183`).

Five places in ``src`` build an adapter that calls Ollama. When this was written
there were four, three of which read the variable; the fourth did not, and passed
no ``base_url`` at all — so a deployment with Ollama on a GPU box got the
embedder, the classifier and the goal judge there, and extraction on a loopback
port with nothing behind it. The fifth is the reviewer (`REV-LOCAL`, `D-266`),
and it arrived correct because this file made the requirement a failing test
rather than a convention.

Nothing related the four, which is why one could drift from three without
anybody noticing. This is the relation, in the shape `D-178` established for the
egress doors: a scan of every ``Ollama*`` construction in ``src``, and a
registry of the builders allowed to make one. It fails in three directions:

* a construction site that is not a registered builder;
* a builder that does not read ``KAE_OLLAMA_URL``, or does not hand what it read
  to the adapter;
* a builder whose ``runtime_profile.require`` classifies the reach of some
  *other* expression than the URL the adapter is given — which would let the
  profile permit a loopback call the adapter then makes elsewhere (`D-172`).

The third is the one that makes honouring the variable safe rather than merely
correct, and it is checked by name-matching rather than by running anything: the
value passed as ``base_url=`` and the value inside ``reach_of_url(...)`` must be
the same local name.

**Not a shared helper.** Four copies of one ``environ.get`` line would collapse
into one function, and this file deliberately does not ask for that: each site
pairs the URL with a different variable name in its refusal, and the pairing is
what the profile check depends on. Pinning the invariant is worth more than
removing the repetition (`D-174` made the same trade about the profile table).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "kae_memory"

VARIABLE = "KAE_OLLAMA_URL"
"""Where this deployment's Ollama is. One answer, every door."""

BUILDERS: Mapping[str, str] = {
    "agents/goal_judge.py::default_goal_judge": "KAE_GOAL_JUDGE",
    "agents/provider.py::build_classifier": "KAE_OBSERVATION_CLASSIFIER",
    "agents/provider.py::build_embedder": "KAE_EMBEDDING",
    "worker/execution.py::default_extractor": "KAE_EXTRACTION",
    "worker/execution.py::default_reviewer": "KAE_REVIEW",
}
"""Module and function that may construct an Ollama adapter → the variable it selects on.

A new local-model capability adds a line here, and adding the line is what makes
the three assertions below apply to it.
"""


def _functions() -> Iterator[tuple[str, ast.FunctionDef]]:
    """Every top-level function in ``src``, keyed ``module::name``."""

    for path in sorted(SRC.rglob("*.py")):
        module = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                yield f"{module}::{node.name}", node


def _constructions(node: ast.AST) -> list[ast.Call]:
    """Calls to a name beginning ``Ollama`` — every adapter this estate has."""

    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id.startswith("Ollama")
    ]


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _reads_the_variable(function: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Constant) and node.value == VARIABLE for node in ast.walk(function)
    )


def _reach_arguments(function: ast.FunctionDef) -> list[ast.expr]:
    """What each ``runtime_profile.require`` in this function classifies the reach of."""

    arguments: list[ast.expr] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if not isinstance(called, ast.Attribute) or called.attr != "require":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if (
            isinstance(first, ast.Call)
            and isinstance(first.func, ast.Attribute)
            and first.func.attr == "reach_of_url"
            and first.args
        ):
            arguments.append(first.args[0])
    return arguments


class TestEveryOllamaAdapterIsBuiltByARegisteredDoor:
    def test_nothing_constructs_one_outside_the_registry(self) -> None:
        stray = sorted(
            name
            for name, function in _functions()
            if _constructions(function) and name not in BUILDERS
        )
        assert not stray, (
            "these functions construct an Ollama adapter and are not registered "
            "local-model doors:\n  "
            + "\n  ".join(stray)
            + f"\nRead {VARIABLE}, hand it to the adapter, refuse on its reach, and "
            "add the function to BUILDERS."
        )

    def test_no_registered_builder_stopped_building_one(self) -> None:
        """A stale entry reads exactly like a door that honours the variable."""

        functions = dict(_functions())
        stale = sorted(
            name
            for name in BUILDERS
            if name not in functions or not _constructions(functions[name])
        )
        assert not stale, "registered here and no longer building an Ollama adapter: " + ", ".join(
            stale
        )


class TestEveryDoorMovesWithTheVariable:
    def test_each_builder_reads_it_and_passes_what_it_read(self) -> None:
        # A registry entry naming no function is the stale case above; reporting
        # it twice as a KeyError here would bury the message that says so.
        functions = dict(_functions())
        for name in BUILDERS.keys() & functions.keys():
            function = functions[name]
            assert _reads_the_variable(function), f"{name} never reads {VARIABLE}"
            for call in _constructions(function):
                given = _keyword(call, "base_url")
                assert isinstance(given, ast.Name), (
                    f"{name} constructs {call.func.id} without passing a base_url name; "  # type: ignore[attr-defined]
                    f"the adapter would use its module literal whatever {VARIABLE} says"
                )

    def test_each_builder_refuses_on_the_reach_of_the_url_it_gives_the_adapter(self) -> None:
        """Otherwise the profile rules on one address and the adapter calls another."""

        functions = dict(_functions())
        for name in BUILDERS.keys() & functions.keys():
            function = functions[name]
            classified = {
                node.id for node in _reach_arguments(function) if isinstance(node, ast.Name)
            }
            for call in _constructions(function):
                given = _keyword(call, "base_url")
                assert isinstance(given, ast.Name) and given.id in classified, (
                    f"{name} hands the adapter a URL whose reach no "
                    f"runtime_profile.require in the same function classifies; "
                    f"reach_of_url is called on {sorted(classified) or 'nothing'}"
                )

    def test_the_selecting_variables_are_the_ones_the_estate_documents(self) -> None:
        """A further door is a real decision, not a line somebody added in passing.

        The fifth was `KAE_REVIEW` (`D-266`), and it was a decision: review was
        the last step in the loop with no local option, so an offline deployment
        classified with a rule that fires for two knowledge kinds of eight.
        """

        assert set(BUILDERS.values()) == {
            "KAE_EMBEDDING",
            "KAE_EXTRACTION",
            "KAE_GOAL_JUDGE",
            "KAE_OBSERVATION_CLASSIFIER",
            "KAE_REVIEW",
        }
