"""Every application capability is reachable from an adapter, or says why not.

**Four capabilities have been found complete, correct, and callable by nothing.**
`reembedding_service` (F-007), module curation (F-006), the assumption model
(N45), and `IngestionService.enqueue_review` (EM-5). The last one made readiness
report 0% on every project in the system, for as long as it existed, and was
found only by loading four real projects and wondering why the number never
moved.

The reason it keeps happening is structural, and worth stating because it is not
obvious:

* **From below**, a service method with passing unit tests looks healthy. Its
  tests call it directly, so they pass whether or not anything else does.
* **From above**, `tests/api/test_adapter_parity.py` checks that every *declared*
  capability exists. It cannot check the converse — that existing behaviour is
  declared — because it starts from the registry.

So the gap is invisible from both ends. This test starts from the *services* and
looks outward, which is the direction nothing else looks.

## What "reachable" means here

**Transitively named**, starting from adapter source. An adapter names an entry
point; that entry point calls deeper methods; those count too.

The transitivity is not optional. The reject route calls
`MemoryService.review_reject`, which calls `reject_knowledge` internally — and a
check that stopped at the adapter would report `reject_knowledge` as unreachable
along with dozens of others. A test that cries wolf gets exempted wholesale,
which is worse than not having it.

It will not catch a method referenced but unreachable behind a condition that is
never true. That is a real limit and it is not the failure mode this exists for.

## Exemptions carry reasons

Same rule the capability registry already applies to asymmetric exposure: an
exception without a reason is indistinguishable from an oversight. Adding a name
here is cheap and deliberate, which is the point — the cost is having to say
why, out loud, where the next person reads it.
"""

from __future__ import annotations

import ast
import inspect
import pkgutil
from importlib import import_module
from pathlib import Path

import pytest

import kae_memory.application as application_package

#: Source that counts as a caller. Anything a request, a tool call, or a queued
#: run can reach.
#:
#: The worker is included after checking that including it does not hide the
#: defect this test exists for: worker source references `enqueue_review` zero
#: times, because the worker *executes* review runs and never *queues* one.
#: Excluding it, on the other hand, reported a dozen legitimately worker-only
#: methods as gaps — and a test that cries wolf gets exempted wholesale.
CALLER_ROOTS = (
    "kae_memory/api",
    "kae_memory/mcp",
    "kae_memory/worker",
    "kae_memory/agents",
)

#: Methods that legitimately have no adapter, and why.
#:
#: Keyed `Service.method`. A reason is mandatory — see the module docstring.
EXEMPT: dict[str, str] = {
    # -- lifecycle, not a product capability ------------------------------
    "ReadinessService.install_template": "bootstrap, run when a project is created",
    #
    # -- superseded by a later path, and kept -----------------------------
    #
    # These are not gaps; they are the *older* of two ways to do one thing.
    # `review_reject` and its siblings route through `_review`, which records
    # the reviewer and the reason, and they are what the adapters call. The
    # plain verbs predate that and survive because deleting a public method on
    # the widest service in the codebase is its own change.
    #
    # Recorded here rather than deleted so the next reader knows which one is
    # live. A second correct-looking path is how a caller ends up bypassing the
    # audit trail without noticing.
    "MemoryService.reject_knowledge": "superseded by review_reject, which records the reviewer",
    "MemoryService.correct_knowledge": "superseded by review_correct",
    "MemoryService.supersede_knowledge": "superseded by review_supersede",
    #
    # -- operational, and genuinely uncalled ------------------------------
    #
    # Embedding migration and chunking have no CLI, no route and no tool. They
    # are run by hand from a Python shell today. That is a real gap and it is
    # F-007's neighbourhood rather than a new finding; recorded so it stops
    # being rediscovered.
    "ReembeddingService.migrate": "operational, invoked by hand; no CLI exists yet",
    "ReembeddingService.outstanding": "operational, invoked by hand",
    "ReembeddingService.release_claims": "operational recovery, invoked by hand",
    "RetrievalService.chunk_knowledge": "operational backfill, invoked by hand",
    "RetrievalService.embed_pending": "operational backfill, invoked by hand",
    #
    # -- implementation details of a reachable method ---------------------
    "RenderService.render": "used by deliverable recording",
    "RetrievalService.best_effort": "the search route's implementation",
    "RetrievalService.indexing_status": "reported inside a search response",
    "AssemblyService.is_stale": "computed into an assembly manifest, not asked for",
    "RenderService.is_still_reproducible": "computed into a deliverable response",
    "RenderService.verify": "the reproduction check's implementation",
    "ClarificationService.asked": "used when materialising the clarification list",
    "ClarificationService.unanswered": "used when materialising the clarification list",
    #
    # -- genuinely unreachable, and tracked elsewhere ---------------------
    #
    # Each of these is a capability the domain models and no caller can reach.
    # They are exempted rather than fixed here because each is somebody's
    # phase, and a test is the wrong place to smuggle in a feature.
    "ModuleService.confirm": "modules are MCP-only by decision — F-006, issue #85",
    "ModuleService.graph": (
        "the module graph tool calls list_modules and build_order; this returns the "
        "graph object and nothing asks for it — F-006"
    ),
    "PublicationService.publish": (
        "live publication is behind the publication-ownership decision — DEP-D7/D9"
    ),
    "SetupService.set_value": "setup writes are unexposed; reads are — DEF/setup work",
    "SetupService.register_target": "setup writes are unexposed",
    "SetupService.record_connection": "setup writes are unexposed",
    "SetupService.resolve_target": "setup writes are unexposed",
    "AssumptionService.reject": "the assumption lifecycle is partly exposed — N45's remainder",
    "AssumptionService.retire": "the assumption lifecycle is partly exposed — N45's remainder",
    "CapabilityReadinessService.report": (
        "the capability report is assembled into other responses rather than served"
    ),
    #
    # -- run lifecycle and history, unreachable ---------------------------
    #
    # The worker drives runs through its own executor rather than these, and
    # nothing serves run history. Interrupt and resume are the interesting
    # pair: the domain models an interrupted run resuming, and no caller can
    # ask for either — so a run that stalls is a run somebody restarts by hand.
    "MemoryService.interrupt_run": "run lifecycle is unexposed; the worker uses its executor",
    "MemoryService.resume_run": (
        "run lifecycle is unexposed — an interrupted run cannot be resumed by a caller"
    ),
    "MemoryService.resumable_runs": "run lifecycle is unexposed",
    "MemoryService.review_history": "review history is modelled and served by nothing",
    "MemoryService.review_history_for_project": "review history is modelled and served by nothing",
    "MemoryService.provenance_for_item": (
        "the trace route builds provenance from the repository directly"
    ),
}


def _service_classes() -> list[type]:
    """Every public service class under `kae_memory.application`."""

    found: list[type] = []
    for module_info in pkgutil.iter_modules(application_package.__path__):
        module = import_module(f"kae_memory.application.{module_info.name}")
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and name.endswith("Service")
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return sorted(set(found), key=lambda c: c.__name__)


def _public_methods(service: type) -> list[str]:
    """Public, service-defined methods. Not dunders, not inherited, not private."""

    return sorted(
        name
        for name, member in vars(service).items()
        if callable(member) and not name.startswith("_")
    )


SRC = Path(__file__).resolve().parents[2] / "src"


def _attributes_in(tree: ast.AST) -> set[str]:
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def _names_used_by_callers() -> set[str]:
    """Every attribute name any caller source refers to.

    Parsed rather than grepped. A regex over source would count a method named
    in a comment or a docstring as reachable, and the comment explaining why
    something is *not* wired would make it look wired.
    """

    used: set[str] = set()
    for caller_root in CALLER_ROOTS:
        for path in (SRC / caller_root).rglob("*.py"):
            used |= _attributes_in(ast.parse(path.read_text(), filename=str(path)))
    return used


def _calls_within_application() -> dict[str, set[str]]:
    """For each application method, the attribute names its body refers to.

    Keyed by bare method name rather than `Service.method`. Two services sharing
    a method name will over-approximate — one's callees will be attributed to
    both — and that is the safe direction: this test reports gaps, so a false
    *negative* costs a missed capability while a false positive costs an
    argument.
    """

    calls: dict[str, set[str]] = {}
    for path in (SRC / "kae_memory" / "application").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        calls.setdefault(item.name, set()).update(_attributes_in(item))
    return calls


def _reachable() -> set[str]:
    """Adapter-named methods, closed over what they call."""

    reachable = _names_used_by_callers()
    calls = _calls_within_application()

    frontier = set(reachable)
    while frontier:
        nxt: set[str] = set()
        for name in frontier:
            for callee in calls.get(name, ()):
                if callee not in reachable:
                    reachable.add(callee)
                    nxt.add(callee)
        frontier = nxt
    return reachable


SERVICES = _service_classes()


def test_the_scan_found_the_services() -> None:
    """Guard the guard.

    If the discovery ever returns nothing — a rename, a package move — every
    test below passes vacuously and the check silently stops running. That is
    the failure mode a test like this dies of.
    """

    assert len(SERVICES) >= 10, f"only found {[s.__name__ for s in SERVICES]}"


@pytest.mark.parametrize("service", SERVICES, ids=lambda s: s.__name__)
def test_every_service_method_is_reachable_or_exempt(service: type) -> None:
    """A capability nothing can call is a capability that does not exist."""

    reachable = _reachable()
    unreachable = [
        f"{service.__name__}.{method}"
        for method in _public_methods(service)
        if method not in reachable and f"{service.__name__}.{method}" not in EXEMPT
    ]

    assert not unreachable, (
        f"no adapter names {unreachable}. Either expose it — a capability entry, "
        f"a route, a tool — or add it to EXEMPT with a reason. Four capabilities "
        f"have already shipped complete and unreachable; this is the check that "
        f"catches the fifth."
    )


def test_every_exemption_names_something_that_exists() -> None:
    """An exemption for a deleted method hides the next one added under that name.

    The registry has the same property and enforces it the same way: a stale
    exception is worse than none, because it reads as considered.
    """

    real = {f"{s.__name__}.{m}" for s in SERVICES for m in _public_methods(s)}
    stale = sorted(set(EXEMPT) - real)

    assert not stale, f"EXEMPT names methods that no longer exist: {stale}"
