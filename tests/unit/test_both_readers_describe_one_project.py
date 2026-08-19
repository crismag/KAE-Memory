"""HTTP and MCP are two readers of one project, and they must say the same thing.

KAE-Memory serves every record twice: a Pydantic model in ``api/schemas.py`` for
the person reading through KAE-Studio, and a dict literal in ``mcp/tools.py`` for
the agent reading over MCP. Nothing relates the two, so a field added to one is a
field the other silently stops carrying.

That is not hypothetical. `D-290` had to add ``revisit`` to both adapters in one
commit because the promise ``keep_open`` makes had reached neither reader, and
the only thing that would have caught the half-done version was somebody
remembering. `D-293` found the survivor of the same shape: the deliverable
``manifest`` — the gap summaries and warnings recorded at generation — was on
the HTTP model and absent from the MCP payload.

Read as ``ast`` rather than by calling the renderers: this runs on the runner in
milliseconds with no database and no server, and a key that only appears under a
particular record's data is still a key.

**Every difference is registered with a reason.** A register nobody enforces is a
gate that is asserted and absent (`D-32`), so the register is checked in both
directions — an unregistered difference fails, and a registered one that has
stopped being true fails too.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field

import kae_memory

SOURCE = pathlib.Path(kae_memory.__file__).parent
TOOLS = SOURCE / "mcp" / "tools.py"
SCHEMAS = SOURCE / "api" / "schemas.py"


@dataclass(frozen=True)
class Pair:
    """One record, rendered twice."""

    payload: str
    """The renderer in ``mcp/tools.py``."""
    model: str
    """The model in ``api/schemas.py`` over the same domain object."""
    nested: str | None = None
    """A key inside the payload, when the entry has no renderer of its own."""
    http_only: frozenset[str] = field(default_factory=frozenset)
    mcp_only: frozenset[str] = field(default_factory=frozenset)
    reason: str = ""


PAIRS: tuple[Pair, ...] = (
    Pair(
        payload="_assumption_payload",
        model="AssumptionResponse",
        http_only=frozenset({"knowledge_changed"}),
        reason=(
            "`knowledge_changed` is what a write did, not what an assumption is. "
            "The MCP tools carry it on their own envelope."
        ),
    ),
    Pair(
        payload="_deliverable_payload",
        model="DeliverableResponse",
        http_only=frozenset({"recorded"}),
        reason=(
            "`recorded` says whether *this call* created the record, which is "
            "not part of the record. `manifest` is (D-293)."
        ),
    ),
    Pair(
        payload="_preliminary_payload",
        model="PreliminaryContextResponse",
        mcp_only=frozenset({"note"}),
        reason=(
            "The note tells an agent that nothing here is confirmed by having "
            "been returned. A person is told that by the page."
        ),
    ),
    Pair(
        payload="_preliminary_payload",
        nested="stated_verbatim",
        model="StatedEntryResponse",
    ),
    Pair(
        payload="_preliminary_payload",
        nested="assumed",
        model="AssumedEntryResponse",
        reason="The hop `D-290` had to fix twice by hand.",
    ),
    Pair(payload="_statement_payload", model="PreliminaryStatementResponse"),
    Pair(payload="_unknown_payload", model="UnknownEntryResponse"),
    Pair(payload="_target_payload", model="PublicationTargetResponse"),
    Pair(
        payload="_ingestion_payload",
        model="IngestionResponse",
        mcp_only=frozenset({"chunks_available", "next_steps", "outstanding_runs"}),
        reason=(
            "Written for a caller that has to decide what to do next with no "
            "surface to look at. Additions, not losses."
        ),
    ),
    Pair(
        payload="_assembly_payload",
        model="AssemblyResponse",
        http_only=frozenset({"knowledge_revision"}),
        reason=(
            "Both readers carry it inside `manifest`; the HTTP model repeats it "
            "at the top level. A repeat is not a second fact."
        ),
    ),
)

UNPAIRED: dict[str, str] = {
    "_classification_payload": (
        "Three payloads in one function — unavailable, failed, classified — and "
        "no HTTP model renders the same three. `ClassificationListResponse` is a "
        "listing of stored classifications, which is a different question."
    ),
    "_module_context_payload": (
        "A bounded context, not a neighbourhood. `ModuleNeighbourhoodResponse` "
        "lists module keys under `satisfies` and `verified_by`; this resolves "
        "them into the statements themselves (N17) and adds the guidance an "
        "agent reads instead of a page. Registering it would take more "
        "exceptions than it has fields."
    ),
}


def _module(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text())


def _payload_functions() -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in _module(TOOLS).body
        if isinstance(node, ast.FunctionDef) and node.name.endswith("_payload")
    }


def _returned_dict(function: ast.FunctionDef) -> ast.Dict:
    returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
    dicts = [node.value for node in returns if isinstance(node.value, ast.Dict)]
    assert len(dicts) == 1, f"{function.name} returns {len(dicts)} dict literals"
    return dicts[0]


def _keys(literal: ast.Dict) -> set[str]:
    return {
        key.value
        for key in literal.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _entry_dict(literal: ast.Dict, key: str) -> ast.Dict:
    """The dict each element of ``key``'s list comprehension is rendered as."""

    for name, value in zip(literal.keys, literal.values, strict=True):
        if isinstance(name, ast.Constant) and name.value == key:
            assert isinstance(value, ast.ListComp), f"{key} is not a comprehension"
            assert isinstance(value.elt, ast.Dict), f"{key} does not render a dict"
            return value.elt
    raise AssertionError(f"no key {key!r} in this payload")


def mcp_keys(pair: Pair) -> set[str]:
    literal = _returned_dict(_payload_functions()[pair.payload])
    if pair.nested is not None:
        literal = _entry_dict(literal, pair.nested)
    return _keys(literal)


def http_fields(name: str) -> set[str]:
    for node in _module(SCHEMAS).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
            }
    raise AssertionError(f"no model named {name} in api/schemas.py")


class TestOneRecordTwoReaders:
    def test_every_registered_pair_names_the_same_fields(self) -> None:
        divergent: list[str] = []
        for pair in PAIRS:
            mcp = mcp_keys(pair)
            http = http_fields(pair.model)
            missing_from_mcp = http - mcp - pair.http_only
            missing_from_http = mcp - http - pair.mcp_only
            where = f"{pair.payload}[{pair.nested}]" if pair.nested else pair.payload
            if missing_from_mcp:
                divergent.append(
                    f"{where} does not carry {sorted(missing_from_mcp)}, which {pair.model} sends"
                )
            if missing_from_http:
                divergent.append(
                    f"{pair.model} does not carry {sorted(missing_from_http)}, which {where} sends"
                )

        assert not divergent, (
            "an agent and a person are being told different things about the "
            "same record — carry the field on both readers, or register the "
            "difference with the reason it is deliberate:\n  " + "\n  ".join(divergent)
        )

    def test_no_registered_difference_has_quietly_become_true(self) -> None:
        """A stale exception is a suppressed comparison nobody chose."""

        stale: list[str] = []
        for pair in PAIRS:
            mcp = mcp_keys(pair)
            http = http_fields(pair.model)
            for name in sorted(pair.http_only & mcp):
                stale.append(f"{pair.payload} now carries {name}: it is no longer HTTP-only")
            for name in sorted(pair.mcp_only & http):
                stale.append(f"{pair.model} now carries {name}: it is no longer MCP-only")

        assert not stale, "\n  ".join(stale)

    def test_every_renderer_is_either_compared_or_registered_as_uncompared(self) -> None:
        """So a tenth renderer cannot arrive and be checked against nothing."""

        rendered = set(_payload_functions())
        accounted = {pair.payload for pair in PAIRS} | set(UNPAIRED)

        assert rendered == accounted, (
            "a payload renderer belongs in PAIRS with its HTTP model, or in "
            f"UNPAIRED with the reason it has none: {sorted(rendered ^ accounted)}"
        )

    def test_every_uncompared_renderer_says_why(self) -> None:
        assert all(reason.strip() for reason in UNPAIRED.values())

    def test_the_scan_reads_the_fields_it_is_asserting_about(self) -> None:
        """A comparison of two empty sets passes for free (`D-219`).

        Both sides are read out of real source, so the control is that they are
        populated at all — and that the field `D-293` added is one of them.
        """

        deliverable = next(pair for pair in PAIRS if pair.payload == "_deliverable_payload")

        assert len(PAIRS) == 10
        assert "manifest" in mcp_keys(deliverable)
        assert "manifest" in http_fields("DeliverableResponse")
        assert len(http_fields("DeliverableResponse")) > 20
