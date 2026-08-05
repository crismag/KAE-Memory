"""Durable identity for an assembled product output (N20).

`assemble_context` produces a description and forgets it. `package_id` is a
fresh UUID per call, deliberately — an assembly is a computation, and giving a
computation an identity that outlives it would invite a client to store an id
that resolves to nothing.

A **deliverable** is the other thing: a durable record that this project
produced this output, at this knowledge revision, with this content. It is what
a person points at when they say "the package we shipped on Tuesday", and what
a later reader compares against to ask whether the project has moved since.

Three properties make it that rather than a second name for an assembly.

**Immutable.** The manifest, the hash, and the artifact index are fixed at
recording. A deliverable that could be edited would let "what we shipped" be
rewritten after the fact, which is precisely the claim it exists to preserve.
Only its lifecycle moves.

**Identified by content, not by call.** Recording the same output twice returns
the same deliverable. Two identical outputs are one deliverable recorded twice,
and a system that minted a second id would report a change that did not happen.

**Never the bytes.** The record holds the manifest, the hashes, and what each
artifact would contain. Rendering and storing the artifact itself is N21, and
putting bytes in a relational row would make the durable record of a decision
compete with a file store for the same job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import DomainInvariantError
from .identifiers import Identifier, ProjectId


@dataclass(frozen=True, slots=True)
class DeliverableId(Identifier):
    """Stable deliverable identifier. Survives the assembly that produced it."""


class DeliverableState(StrEnum):
    """Where a deliverable stands.

    Not a rendering or publication state — those belong to N21 and to whoever
    owns the destination. This says whether the record still represents
    something the project stands behind.
    """

    RECORDED = "recorded"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


_ALLOWED_TRANSITIONS: dict[DeliverableState, frozenset[DeliverableState]] = {
    DeliverableState.RECORDED: frozenset({DeliverableState.SUPERSEDED, DeliverableState.WITHDRAWN}),
    # Terminal. A superseded deliverable that could return to current would make
    # the supersession chain unreadable — two records would each claim to be the
    # latest, and neither would be wrong from its own row.
    DeliverableState.SUPERSEDED: frozenset(),
    DeliverableState.WITHDRAWN: frozenset(),
}


class InvalidDeliverableTransitionError(DomainInvariantError):
    """A deliverable state change the domain does not permit."""


def ensure_deliverable_transition(current: DeliverableState, target: DeliverableState) -> None:
    """Validate a requested deliverable state change."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        allowed = sorted(state.value for state in _ALLOWED_TRANSITIONS[current])
        raise InvalidDeliverableTransitionError(
            f"cannot move a deliverable from {current.value} to {target.value}; "
            f"permitted: {', '.join(allowed) or 'none, this state is terminal'}"
        )


ORDERING_CONTRACT = "areas-by-purpose.v1"
"""How sections and statements are ordered, named so a change is legible.

The artifact hash already fails when ordering changes, but it fails without
saying why. A caller comparing two hashes learns that reproduction is
impossible; a caller comparing two ordering contracts learns that the renderer
reorders differently now, which is a different problem with a different remedy.
"""


@dataclass(frozen=True, slots=True)
class StatementPin:
    """One statement, at the exact version that was rendered.

    The identifier alone is not enough. Assembly reads `current_version`, so a
    later correction changes what a re-render produces while the recorded
    identifier stays the same — the deliverable would appear reproducible and
    would not be.

    Knowledge versions are immutable and append-only, which is what makes this
    a pin rather than a hope: the version this names still exists, unchanged,
    however far the statement has moved since.
    """

    knowledge_id: str
    version: int

    def __post_init__(self) -> None:
        if not self.knowledge_id.strip():
            raise DomainInvariantError("a pin needs a knowledge identifier")
        if self.version < 1:
            raise DomainInvariantError(f"version {self.version} is not a version number")


@dataclass(frozen=True, slots=True)
class RenderInputs:
    """Everything other than the statements that determines the output.

    Pinning versions alone would still leave a deliverable irreproducible,
    because the same statements rendered under a different purpose, a different
    proposed-inclusion setting, a different ordering contract, or a different
    generator produce different bytes. Each of these is an input, and an input
    that is not recorded is an input that cannot be reproduced.

    `structural_fingerprint` covers the module graph, which decides what a
    module-scoped assembly contains. It is `None` for project scope, where the
    graph does not participate — recorded as absent rather than as an empty
    string, so "no structure involved" and "structure not captured" stay
    distinguishable.
    """

    purpose: str
    scope: str
    include_proposed: bool
    ordering_contract: str
    generator_version: str
    package_schema: str
    knowledge_revision: int
    module_key: str | None = None
    structural_fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "scope": self.scope,
            "include_proposed": self.include_proposed,
            "ordering_contract": self.ordering_contract,
            "generator_version": self.generator_version,
            "package_schema": self.package_schema,
            "knowledge_revision": self.knowledge_revision,
            "module_key": self.module_key,
            "structural_fingerprint": self.structural_fingerprint,
        }

    @classmethod
    def from_dict(cls, stored: dict[str, Any]) -> RenderInputs | None:
        """Rebuild inputs from a stored record, or ``None`` if they were never captured.

        A partially captured set is treated as absent. Reproduction needs every
        input; a subset would let a deliverable claim eligibility it cannot
        honour, which is the failure this whole target exists to prevent.
        """

        required = (
            "purpose",
            "scope",
            "include_proposed",
            "ordering_contract",
            "generator_version",
            "package_schema",
            "knowledge_revision",
        )
        if not stored or any(field not in stored for field in required):
            return None
        return cls(
            purpose=str(stored["purpose"]),
            scope=str(stored["scope"]),
            include_proposed=bool(stored["include_proposed"]),
            ordering_contract=str(stored["ordering_contract"]),
            generator_version=str(stored["generator_version"]),
            package_schema=str(stored["package_schema"]),
            knowledge_revision=int(stored["knowledge_revision"]),
            module_key=stored.get("module_key"),
            structural_fingerprint=stored.get("structural_fingerprint"),
        )


LEGACY_INELIGIBLE = (
    "recorded before render inputs were captured (N20.1): the exact statement "
    "versions and rendering options it used cannot be proven, so re-rendering "
    "it could produce different content under its original identity"
)
"""Why a pre-N20.1 deliverable cannot be published.

Stated on the record rather than inferred by a caller. These deliverables stay
readable — what they were and when is still true — and nothing fabricates the
versions they used, because a guessed pin is worse than an absent one: it would
make an unprovable claim look proven.
"""


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """What one artifact of a deliverable would contain.

    A description, never the content. `content_hash` is what lets a renderer
    later prove that what it wrote matches what was recorded, without this
    table ever having held the bytes.
    """

    path: str
    area_key: str
    title: str
    statement_count: int
    confirmed_count: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class Deliverable:
    """A durable record of an assembled product output."""

    id: DeliverableId
    project_id: ProjectId
    purpose: str
    scope: str
    knowledge_revision: int
    content_hash: str
    artifacts: tuple[ArtifactRecord, ...]
    state: DeliverableState = DeliverableState.RECORDED
    module_key: str | None = None
    generator_version: str = ""
    source_knowledge: tuple[str, ...] = ()
    recorded_by: str | None = None
    recorded_at: datetime | None = None
    superseded_by: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    statement_pins: tuple[StatementPin, ...] = ()
    render_inputs: RenderInputs | None = None
    qualification: dict[str, Any] | None = None
    """What this was produced *for*, and what a person accepted (N38).

    Alongside the identity rather than inside it. Identity says what was
    produced; this says what it was produced for and what a reader should know
    before acting on it. Immutability describes the first and claims nothing
    about completeness.
    """

    def __post_init__(self) -> None:
        if not self.content_hash.strip():
            raise DomainInvariantError(
                "a deliverable needs a content hash: without one it cannot be "
                "compared to what was later rendered, or to another deliverable"
            )
        if self.knowledge_revision < 0:
            raise DomainInvariantError("a knowledge revision cannot be negative")
        if self.scope == "module" and not self.module_key:
            raise DomainInvariantError("a module-scoped deliverable must name its module")

    def is_stale_against(self, current_revision: int) -> bool:
        """Whether the project has moved since this was recorded.

        Derived, never stored. A stored staleness flag is true until something
        remembers to update it, and the thing most likely to forget is the
        write that made it false.
        """

        return current_revision > self.knowledge_revision

    @property
    def is_current(self) -> bool:
        return self.state is DeliverableState.RECORDED

    @property
    def publication_eligible(self) -> bool:
        """Whether this deliverable can be re-rendered and proven identical.

        Requires pinned statement versions *and* the full render inputs. A
        deliverable holding one without the other is not partially reproducible
        — it is unreproducible with extra detail.

        The artifact hashes remain the final proof. Eligibility says the inputs
        exist to attempt reproduction; the hash says whether the attempt
        succeeded, and only the hash can say that.
        """

        return bool(self.statement_pins) and self.render_inputs is not None

    @property
    def ineligibility_reason(self) -> str | None:
        """Why this deliverable cannot be published, or ``None`` if it can."""

        if self.publication_eligible:
            return None
        return LEGACY_INELIGIBLE


def identity_hash(
    project_id: ProjectId,
    purpose: str,
    scope: str,
    module_key: str | None,
    knowledge_revision: int,
    content_hash: str,
) -> str:
    """Return the fingerprint two identical recordings share.

    Recording the same output twice is one deliverable recorded twice. Minting
    a second id would report a change the project did not make, and a consumer
    diffing deliverable ids would see churn that means nothing.

    The knowledge revision is part of it deliberately: the same content at a
    later revision is a genuinely different claim, because it says the project
    moved and the output did not.
    """

    from hashlib import sha256

    parts = (
        str(project_id),
        purpose,
        scope,
        module_key or "",
        str(knowledge_revision),
        content_hash,
    )
    return sha256("|".join(parts).encode()).hexdigest()
