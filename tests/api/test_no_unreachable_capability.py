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

**Named on a resolved receiver** (`D-261`). Reachability is keyed
`Service.method`, not `method`. It used to be the bare name, which made this
check service-blind in both directions: `SourceService.stop_reading` being called
made `AssumptionService.stop_reading` read as reachable, and an attribute read on
a *response object* — `record.material`, `module.summary` — counted as evidence
that the service method of that name had a caller. Three capabilities were
hiding in that gap and are exempted below.

The receiver is resolved from source because this estate calls services through
four shapes and no others: a dependency alias (`sources: Sources`), a container
attribute (`context.memory`), a service attribute (`self._sources`), and a
construction (`ReadinessService(factory).knowledge_revision(...)`). Each has a
self-test at the bottom of this file, so losing one in a later rewrite fails a
test that names the shape instead of surfacing as a gap somebody exempts.

**An unresolved receiver names nothing.** Keeping the bare name as a fallback
would preserve the defect at smaller scale, and this check reports gaps — so the
conservative direction is the one that costs a missed capability, not the one
that costs an argument.

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
    # Same category, and it was invisible until the receiver was resolved
    # (`D-261`): `SynthesisRepository.list_bindings` is called by the service
    # method one layer above it, so a scan keyed on the bare name reported the
    # service method as reached by its own callee's namesake.
    #
    # `GET /model/{object_id}` is the live read. It answers through
    # `get_object`, whose view carries what each bound statement *says* —
    # `D-144`, because *what supports this* cannot be answered with a list of
    # identifiers, which is what this returns.
    "SynthesisService.list_bindings": (
        "superseded by get_object's evidence view, which carries the statements (D-144)"
    ),
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
    #
    # -- described as reached, and reached by nothing ----------------------
    #
    # Found by splitting this dictionary in two (`D-20`). Each of these sat
    # under a comment reading *"implementation details of a reachable method"*
    # with a sentence naming its caller, and the caller does not exist. The
    # sentences were plausible, specific, and false — which is why they were
    # never questioned.
    #
    # This is the eighth instance of the defect this file was written to catch,
    # and it was inside the file's own exemption list.
    "AssemblyService.is_stale": (
        "described as computed into an assembly manifest; nothing calls it. "
        "`AssemblyManifest.is_stale_against` is the one in use"
    ),
    "ClarificationService.asked": (
        "described as used when materialising the clarification list; nothing calls it"
    ),
    "ClarificationService.unanswered": (
        "described as used when materialising the clarification list; nothing calls it"
    ),
    "RenderService.is_still_reproducible": (
        "described as computed into a deliverable response; nothing calls it"
    ),
    # These two are reachable only through `publication_service.publish`, which
    # is itself unreachable behind the publication-ownership decision. Same
    # shape as `SetupService.resolve_target` below, and stated the same way:
    # the fact a reader needs is *why*, not just that nothing calls it.
    "RenderService.render": (
        "called by RenderService.verify — unreachable only because publication is"
    ),
    "RenderService.verify": (
        "called by publication_service.publish — unreachable only because publication is"
    ),
    #
    # -- genuinely unreachable, and tracked elsewhere ---------------------
    #
    # Each of these is a capability the domain models and no caller can reach.
    # They are exempted rather than fixed here because each is somebody's
    # phase, and a test is the wrong place to smuggle in a feature.
    "ModuleService.confirm": "modules are MCP-only by decision — F-006, issue #85",
    # Also F-006's neighbourhood, and also only visible once the receiver was
    # resolved: `get` is the most collided method name in the codebase, so the
    # bare-name scan reported it as reached by every unrelated `.get(` in the
    # estate. The MCP surface exposes the listing and the graph; one module by
    # key is reachable from nothing.
    "ModuleService.get": "modules are MCP-only, and the tools expose the listing and the graph",
    "PublicationService.publish": (
        "live publication is behind the publication-ownership decision — DEP-D7/D9"
    ),
    # Unreachable for the same reason `publish` is, and stated the same way: the
    # fact a reader needs is *why*. Found by `D-261`, hidden until then by
    # `ReadinessService.history`, which is served.
    "PublicationService.history": (
        "every attempt including the failures — unreachable only because publication is"
    ),
    # `SETUP-ASK-NODOOR`, and the sharpest evidence that the bare-name scan was
    # worth fixing: `D-240` found these two by reading, while this file — the
    # check that exists to find exactly this — stayed green, because
    # `ClarificationService.ask` and `.answer` are both routed and the scan
    # could not tell one service's method from another's.
    #
    # `setup.questions` ships at both exposures, `ask` writes the only rows it
    # can return, and `answer` is the only thing that settles one. The route
    # answers `[]` in every deployment that exists. Giving either a door is an
    # exposure ruling and the owner's.
    "SetupService.ask": "writes the only rows setup.questions returns; no door — SETUP-ASK-NODOOR",
    "SetupService.answer": "settles a setup question, and nothing reaches it — SETUP-ASK-NODOOR",
    # Not a write, and not uncalled: `publication_service.publish` uses it. It
    # is unreachable only because *that* is, which is a different fact and the
    # one a reader needs — F-022 recorded it as unreached, and that was wrong.
    "SetupService.resolve_target": (
        "read, and called by publication_service.publish — unreachable only because publication is"
    ),
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
    #
    # -- synthesis layer reads that sit behind a write ----------------------
    #
    # Role is set over HTTP. This getter is for synthesizers and tests; serving
    # it as its own route would imply a product surface that does not exist yet.
    "SynthesisService.evidence_role": (
        "read helper for the evidence-role table; POST .../evidence-role is the write"
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


#: Methods that **are** reached, through another method rather than directly.
#:
#: Listed for the reader, not exempted from anything — they pass the reachability
#: check on their own merit, and the assertion below holds them to that.
#:
#: They used to sit in `EXEMPT` under a comment saying so, which made the list
#: two different claims in one dictionary: *"nothing calls this"* and *"something
#: calls this, indirectly"*. The obsolescence check could not be written against
#: a list meaning both.
REACHED_INDIRECTLY: dict[str, str] = {
    "RetrievalService.best_effort": "the search route's implementation",
    "RetrievalService.indexing_status": "reported inside a search response",
}


SRC = Path(__file__).resolve().parents[2] / "src"
APPLICATION = SRC / "kae_memory" / "application"

#: A call site, resolved: the class the receiver holds and the attribute named.
Pair = tuple[str, str]


class _Types:
    """What the source says each name holds.

    Three tables, all of them read out of annotations and constructor calls
    rather than guessed:

    * `aliases` — a module-level name bound to a class, which is how the
      dependency aliases work: `Sources = Annotated[SourceService, ...]`.
    * `attributes` — `class -> {attribute: class}`, from annotated fields and
      from `self.x = <constructed or annotated-parameter>` in any method.
    * `returns` — a function name to the class it is annotated as returning,
      so `context = build_context(url)` resolves.

    Names, not qualified paths. Two classes in this codebase sharing a name
    would collapse here, and none do — asserted below rather than assumed,
    because that assumption failing is exactly the shape of defect this file
    exists for.
    """

    def __init__(self) -> None:
        self.classes: set[str] = set()
        self.bases: dict[str, list[str]] = {}
        self.aliases: dict[str, str] = {}
        self.attributes: dict[str, dict[str, str]] = {}
        self.returns: dict[str, str] = {}

    def of_annotation(self, node: ast.expr | None) -> str | None:
        """The class an annotation names, through aliases and string forms."""

        if node is None:
            return None
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and sub.attr in self.classes:
                return sub.attr
            if isinstance(sub, ast.Name):
                if sub.id in self.classes:
                    return sub.id
                if sub.id in self.aliases:
                    return self.aliases[sub.id]
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                try:
                    inner = ast.parse(sub.value, mode="eval").body
                except SyntaxError:
                    continue
                found = self.of_annotation(inner)
                if found is not None:
                    return found
        return None

    def of_construction(self, node: ast.expr | None) -> str | None:
        """The class an expression constructs, including `x or XService(f)`."""

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in self.classes:
                return func.id
            if isinstance(func, ast.Attribute) and func.attr in self.classes:
                return func.attr
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            return self.returns.get(called) if called else None
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                found = self.of_construction(value)
                if found is not None:
                    return found
        return None

    def attribute_of(self, owner: str, attribute: str) -> str | None:
        """An attribute's class, looked up through the owner's bases."""

        pending = [owner]
        while pending:
            current = pending.pop(0)
            found = self.attributes.get(current, {}).get(attribute)
            if found is not None:
                return found
            pending.extend(self.bases.get(current, ()))
        return None


def _class_names(trees: list[ast.Module]) -> set[str]:
    return {
        node.name for tree in trees for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }


def _learn(types: _Types, tree: ast.Module) -> None:
    """Fill the three tables from one module."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                found = types.of_annotation(node.value)
                if found is not None:
                    types.aliases[target.id] = found
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found = types.of_annotation(node.returns)
            if found is not None:
                types.returns[node.name] = found
        if not isinstance(node, ast.ClassDef):
            continue
        types.bases[node.name] = [base.id for base in node.bases if isinstance(base, ast.Name)]
        attributes = types.attributes.setdefault(node.name, {})
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                found = types.of_annotation(item.annotation)
                if found is not None:
                    attributes[item.target.id] = found
            if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            parameters = {
                argument.arg: types.of_annotation(argument.annotation)
                for argument in [*item.args.args, *item.args.kwonlyargs]
            }
            for sub in ast.walk(item):
                if not isinstance(sub, ast.Assign) or len(sub.targets) != 1:
                    continue
                target = sub.targets[0]
                if not (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    continue
                found = types.of_construction(sub.value)
                if found is None and isinstance(sub.value, ast.Name):
                    found = parameters.get(sub.value.id)
                if found is not None:
                    attributes[target.attr] = found


def _resolve(
    types: _Types, function: ast.FunctionDef | ast.AsyncFunctionDef, enclosing: str | None
) -> set[Pair]:
    """Every attribute this function names, on a receiver we could resolve."""

    scope: dict[str, str] = {}
    for argument in [*function.args.args, *function.args.kwonlyargs]:
        found = types.of_annotation(argument.annotation)
        if found is not None:
            scope[argument.arg] = found

    def receiver(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return enclosing if node.id == "self" else scope.get(node.id)
        if isinstance(node, ast.Call):
            return types.of_construction(node)
        if isinstance(node, ast.Attribute):
            owner = receiver(node.value)
            return types.attribute_of(owner, node.attr) if owner else None
        return None

    for sub in ast.walk(function):
        if isinstance(sub, ast.Assign) and len(sub.targets) == 1:
            target = sub.targets[0]
            if isinstance(target, ast.Name):
                found = types.of_construction(sub.value) or receiver(sub.value)
                if found is not None:
                    scope[target.id] = found

    named: set[Pair] = set()
    for sub in ast.walk(function):
        if isinstance(sub, ast.Attribute):
            owner = receiver(sub.value)
            if owner is not None:
                named.add((owner, sub.attr))
    return named


def _functions(tree: ast.Module) -> list[tuple[str | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Top-level functions and methods, each with the class it is defined in."""

    found: list[tuple[str | None, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.append((None, node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    found.append((node.name, item))
    return found


def _parsed(root: Path) -> dict[Path, ast.Module]:
    return {
        path: ast.parse(path.read_text(), filename=str(path)) for path in sorted(root.rglob("*.py"))
    }


def _types_for(trees: dict[Path, ast.Module]) -> _Types:
    types = _Types()
    types.classes = _class_names(list(trees.values()))
    # Twice: aliases and return annotations are read in file order, and a router
    # annotating `sources: Sources` is parsed before `dependencies.py` defines
    # the alias. One pass would resolve whatever came first and silently drop
    # the rest, which is the failure this file exists to refuse.
    for _ in range(2):
        for tree in trees.values():
            _learn(types, tree)
    return types


def _named_by_callers(types: _Types, trees: dict[Path, ast.Module]) -> set[Pair]:
    """Every resolved pair any caller source names.

    Parsed rather than grepped. A regex over source would count a method named
    in a comment or a docstring as reachable, and the comment explaining why
    something is *not* wired would make it look wired.
    """

    named: set[Pair] = set()
    for path, tree in trees.items():
        if not any(str(path).startswith(str(SRC / root)) for root in CALLER_ROOTS):
            continue
        for enclosing, function in _functions(tree):
            named |= _resolve(types, function, enclosing)
    return named


def _calls_within_application(
    types: _Types, trees: dict[Path, ast.Module]
) -> dict[Pair, set[Pair]]:
    """For each application method, the resolved pairs its body names."""

    calls: dict[Pair, set[Pair]] = {}
    for path, tree in trees.items():
        if not str(path).startswith(str(APPLICATION)):
            continue
        for enclosing, function in _functions(tree):
            if enclosing is None:
                continue
            calls.setdefault((enclosing, function.name), set()).update(
                _resolve(types, function, enclosing)
            )
    return calls


def _reachable() -> set[str]:
    """Adapter-named `Service.method` keys, closed over what they call."""

    trees = _parsed(SRC / "kae_memory")
    types = _types_for(trees)

    reachable = _named_by_callers(types, trees)
    calls = _calls_within_application(types, trees)

    frontier = set(reachable)
    while frontier:
        nxt: set[Pair] = set()
        for pair in frontier:
            for callee in calls.get(pair, ()):
                if callee not in reachable:
                    reachable.add(callee)
                    nxt.add(callee)
        frontier = nxt
    return {f"{owner}.{attribute}" for owner, attribute in reachable}


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
        if f"{service.__name__}.{method}" not in reachable
        and f"{service.__name__}.{method}" not in EXEMPT
    ]

    assert not unreachable, (
        f"no adapter names {unreachable}. Either expose it — a capability entry, "
        f"a route, a tool — or add it to EXEMPT with a reason. Seven capabilities "
        f"have shipped complete and unreachable; this is the check that catches "
        f"the eighth."
    )


def test_no_exemption_is_obsolete() -> None:
    """An exemption for a method that became reachable reads as considered.

    The other half of the check below, and it did not exist. This file argues
    that an exception without a reason is indistinguishable from an oversight —
    and an exception whose reason **stopped being true** is worse than both,
    because it is a sentence asserting the current state of the system that
    nobody re-reads.

    Four entries were stale when this was written. `SetupService.set_value`,
    `register_target` and `record_connection` said *"setup writes are
    unexposed"* after the POST routes shipped; `ModuleService.graph` said
    *"nothing asks for it"* while `GET /modules/graph` asked for it. Every one
    of those sentences was true when written, which is the whole difficulty.
    """

    reachable = _reachable()
    obsolete = sorted(name for name in EXEMPT if name in reachable)

    assert not obsolete, (
        f"these are exempted as unreachable and something now calls them: {obsolete}. "
        f"Remove the entry — a reason that has stopped being true is worse than no "
        f"reason, because it reads as considered."
    )


def test_a_method_listed_as_reached_indirectly_really_is() -> None:
    """The mirror. A method here that stopped being called is a live gap.

    Without this, moving the indirect entries out of `EXEMPT` would have made
    them invisible to both checks — the reachability test skips nothing now, so
    it would catch them, but only as an anonymous name in a list. This says
    which claim broke.
    """

    reachable = _reachable()
    unreached = sorted(name for name in REACHED_INDIRECTLY if name not in reachable)

    assert not unreached, (
        f"listed as reached through another method, and nothing reaches them: {unreached}"
    )


def test_every_exemption_names_something_that_exists() -> None:
    """An exemption for a deleted method hides the next one added under that name.

    The registry has the same property and enforces it the same way: a stale
    exception is worse than none, because it reads as considered.
    """

    real = {f"{s.__name__}.{m}" for s in SERVICES for m in _public_methods(s)}
    stale = sorted((set(EXEMPT) | set(REACHED_INDIRECTLY)) - real)

    assert not stale, f"EXEMPT names methods that no longer exist: {stale}"


# -- the resolver, one test per call shape ---------------------------------
#
# `D-261` refuses a bare-name fallback for a receiver that will not resolve, so
# a call shape this resolver stops understanding shows up as a capability
# reported unreachable — and gets answered with an exemption that is not true.
# These are what turn that into a failure naming the shape instead.
#
# Each synthetic module defines the classes it calls, so nothing here depends on
# the real tree still having a service of any particular name.


def _resolved_pairs(source: str) -> set[Pair]:
    """Every `(class, attribute)` the resolver can see in one module."""

    tree = ast.parse(source)
    types = _types_for({Path("synthetic.py"): tree})
    return {
        pair
        for enclosing, function in _functions(tree)
        for pair in _resolve(types, function, enclosing)
    }


def test_a_dependency_alias_resolves() -> None:
    """`Sources = Annotated[SourceService, ...]`, then `sources: Sources`."""

    pairs = _resolved_pairs(
        "class SourceService:\n"
        "    def register(self): ...\n"
        "Sources = Annotated[SourceService, Depends(get_sources)]\n"
        "def route(sources: Sources):\n"
        "    return sources.register()\n"
    )

    assert ("SourceService", "register") in pairs


def test_a_container_attribute_resolves() -> None:
    """`context.memory`, where the container's `__init__` annotates it."""

    pairs = _resolved_pairs(
        "class MemoryService:\n"
        "    def list_projects(self): ...\n"
        "class ToolContext:\n"
        "    def __init__(self, memory: MemoryService) -> None:\n"
        "        self.memory = memory\n"
        "def tool(context: ToolContext):\n"
        "    return context.memory.list_projects()\n"
    )

    assert ("MemoryService", "list_projects") in pairs


def test_a_service_attribute_resolves() -> None:
    """`self._sources`, from the one constructor shape every service uses."""

    pairs = _resolved_pairs(
        "class SourceService:\n"
        "    def material(self): ...\n"
        "class IngestionService:\n"
        "    def __init__(self, factory, sources=None):\n"
        "        self._sources = sources or SourceService(factory)\n"
        "    def ingest(self):\n"
        "        return self._sources.material()\n"
    )

    assert ("SourceService", "material") in pairs
    # `self` resolving to the enclosing class is the transitive half: it is what
    # closes a route's entry point over the deeper methods it calls.
    assert ("IngestionService", "_sources") in pairs


def test_a_construction_resolves_immediately_and_through_a_name() -> None:
    """The worker's two shapes: assigned, and called on the constructor."""

    pairs = _resolved_pairs(
        "class ReadinessService:\n"
        "    def knowledge_revision(self): ...\n"
        "class MemoryService:\n"
        "    def get_project(self): ...\n"
        "def execute(self):\n"
        "    memory = MemoryService(self.session_factory)\n"
        "    memory.get_project()\n"
        "    return ReadinessService(self.session_factory).knowledge_revision()\n"
    )

    assert ("MemoryService", "get_project") in pairs
    assert ("ReadinessService", "knowledge_revision") in pairs


def test_an_inherited_attribute_resolves() -> None:
    """A subclass calling through a base class's attribute."""

    pairs = _resolved_pairs(
        "class MemoryService:\n"
        "    def start_run(self): ...\n"
        "class _Agent:\n"
        "    def __init__(self, service: MemoryService) -> None:\n"
        "        self._service = service\n"
        "class ArchitectureAgent(_Agent):\n"
        "    def run(self):\n"
        "        return self._service.start_run()\n"
    )

    assert ("MemoryService", "start_run") in pairs


def test_one_service_being_called_does_not_reach_its_namesake() -> None:
    """The defect this resolver exists for, as a regression (`D-254`, `D-261`).

    Two services hold a method of one name and one of them is called. Under the
    bare-name scan both read as reachable, which is how `AssumptionService.retire`
    passed while nothing could call it.
    """

    pairs = _resolved_pairs(
        "class SourceService:\n"
        "    def stop_reading(self): ...\n"
        "class AssumptionService:\n"
        "    def stop_reading(self): ...\n"
        "Sources = Annotated[SourceService, Depends(get_sources)]\n"
        "def route(sources: Sources):\n"
        "    return sources.stop_reading()\n"
    )

    assert ("SourceService", "stop_reading") in pairs
    assert ("AssumptionService", "stop_reading") not in pairs


def test_an_unresolved_receiver_names_nothing() -> None:
    """An attribute read on a response object is not a call on a service.

    The other half of the same defect, and the more common one in this codebase:
    `record.material` and `module.summary` are domain objects, and under the
    bare-name scan they made `SourceService.material` and `ModuleService.summary`
    look called.
    """

    pairs = _resolved_pairs(
        "class SourceService:\n"
        "    def material(self): ...\n"
        "def route(record):\n"
        "    return record.material\n"
    )

    assert ("SourceService", "material") not in pairs
