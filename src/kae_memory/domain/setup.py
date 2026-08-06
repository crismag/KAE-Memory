"""Preliminary setup: how a project becomes configured, not how it becomes known (N24).

Two different readinesses, and the reason this file exists is that they had been
one. **Knowledge readiness** asks how well understood a project is; it is
advisory and never blocks. **Setup readiness** asks whether the machinery a
requested operation needs is in place — a publication target, an authorised
connection — and it genuinely can be unavailable.

Reporting them together would let either lie about the other. A project with a
clear brief and no GitHub authorisation is fully understood and cannot publish;
a project with a working S3 connection and one sentence of knowledge can publish
something thin. Neither is "60% ready".

The line this file holds: **only setup can block, and only for the five reasons
N34 named** — an unmade choice, missing authorisation, an integrity failure, an
unavailable provider, or an unsupported feature. Nothing here may block because
knowledge is sparse. That is the gate the product context rejected, and a
setup-shaped version of it would be the same gate with a new name.

Nothing here asks a question, names a provider, or reads configuration. It is
vocabulary, so that N25, N26, N27, and N28 build on words that already agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .errors import DomainInvariantError


class SetupState(StrEnum):
    """How far a project's configuration has got.

    Ordered by how much has been established, and deliberately not a
    percentage: "nobody has said where this publishes" and "the connection we
    had stopped working" are different situations with different remedies, and
    one number cannot tell them apart.
    """

    NOT_STARTED = "not_started"
    """Nothing has been established, and nothing has been attempted."""

    DISCOVERING = "discovering"
    """KAE is inferring what it can from what it has been given."""

    NEEDS_INPUT = "needs_input"
    """Something genuinely blocking is missing and only a person can supply it."""

    SUFFICIENT_TO_BEGIN = "sufficient_to_begin_acquisition"
    """Enough to start taking information in. **The common early state**, and
    it is not a deficiency: a project described in one sentence is here, and
    everything KAE does for a sparse project works from here."""

    READY_FOR_GENERATION = "ready_for_generation"
    """Enough to assemble and render. Note that generation never *required*
    this — it is a description of what is configured, not a permission."""

    READY_FOR_PUBLICATION = "ready_for_publication"
    """A target exists, is authorised, and its provider is reachable."""

    DEGRADED = "degraded"
    """Something that worked has stopped. Distinct from `needs_input`, which
    never worked: the remedy for one is repair and for the other is a decision,
    and telling a person to choose a target they already chose is how a system
    teaches people to ignore it."""


BLOCKING_STATES: frozenset[SetupState] = frozenset({SetupState.NEEDS_INPUT})
"""The only setup state that stops an operation on its own.

`degraded` is deliberately absent. A degraded connection blocks the operation
that needs *that provider*, which the capability report says per capability;
treating it as a global block would stop a project from generating a document
because its S3 credentials expired.
"""


class InferencePolicy(StrEnum):
    """What KAE may do when it can work out a value nobody supplied.

    A typed rule rather than prose, because the difference between adopting a
    value and asking about one is the difference between a system that gets out
    of the way and one that decides on a person's behalf — and prose lets that
    line move a little with each implementation.
    """

    ADOPT_AND_DISCLOSE = "adopt_and_disclose"
    """Use it, and say so wherever it matters. For values that are obvious,
    reversible, and cheap to be wrong about."""

    PROPOSE = "propose"
    """Offer it as a suggestion attached to a question. The person decides;
    KAE has done the work of finding a sensible answer."""

    ASK = "ask"
    """Ask without suggesting. For values where a suggestion would anchor a
    decision that ought to be made freshly."""

    DEFER = "defer"
    """Leave it unknown and carry on. The right answer for anything not needed
    until an operation nobody has requested."""

    BLOCK = "block"
    """Refuse the operation until a person supplies it. **Reserved.** See
    `NEVER_INFERRED` — this is the policy for credentials and authorisation,
    and for nothing else."""


NEVER_INFERRED: frozenset[str] = frozenset(
    {
        "credential",
        "secret",
        "token",
        "password",
        "authorization",
        "authorisation",
        "access_key",
        "private_key",
    }
)
"""Field-name fragments KAE must never infer a value for, at any policy.

Not a style rule. An inferred credential is a guess at something that either
grants access it should not or fails in a way that looks like a bug; an
inferred authorisation is KAE deciding it has permission. Both are refused by
`ensure_inferable` rather than left to each implementation to remember.
"""


class SetupError(DomainInvariantError):
    """A setup value or transition is not one this model permits."""


def ensure_inferable(field_name: str, policy: InferencePolicy) -> None:
    """Refuse to infer what must be granted.

    Checked on the field name rather than on the value, because the value is
    exactly what must never exist. A caller that got as far as having a
    credential to check has already made the mistake.
    """

    lowered = field_name.lower()
    if any(fragment in lowered for fragment in NEVER_INFERRED):
        if policy is not InferencePolicy.BLOCK:
            raise SetupError(
                f"{field_name} cannot be inferred under {policy.value}: a credential "
                f"or authorisation is granted, never worked out. Use "
                f"{InferencePolicy.BLOCK.value} and ask."
            )


class ValueState(StrEnum):
    """What is known about one configuration field.

    Nine states because a configuration field genuinely has nine situations,
    and the ones that look redundant are the ones that matter most. `unknown`
    and `deferred` both mean "no value": the first is a gap, the second is a
    decision not to have one yet, and a system that conflates them keeps asking
    about the second. `inferred` and `suggested` are both KAE's work: one is in
    use, the other is waiting for a person.
    """

    UNKNOWN = "unknown"
    INFERRED = "inferred"
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    DEFERRED = "deferred"
    INHERITED = "inherited"
    OVERRIDDEN = "overridden"
    UNAVAILABLE = "unavailable_because_disabled"


IN_USE: frozenset[ValueState] = frozenset(
    {
        ValueState.INFERRED,
        ValueState.CONFIRMED,
        ValueState.PROVISIONAL,
        ValueState.INHERITED,
        ValueState.OVERRIDDEN,
    }
)
"""States where a value actually takes effect.

`suggested` is absent, and that is the whole point of having it: a suggestion
is what KAE would choose, not what it chose. A projection that treated the two
alike would let a proposal configure a system nobody configured.
"""


DISCLOSED: frozenset[ValueState] = frozenset(
    {ValueState.INFERRED, ValueState.PROVISIONAL, ValueState.OVERRIDDEN}
)
"""States that must be disclosed wherever the output they shaped is disclosed.

An inferred value in use is an assumption in everything but name, and the same
rule applies: a reader who cannot tell what KAE worked out from what a person
said will read the first as the second.
"""


@dataclass(frozen=True, slots=True)
class InferredValue:
    """One value KAE worked out, with what it worked it out from.

    `evidence` and `confidence` are required rather than optional. An inference
    nobody can check is indistinguishable from a guess, and a confidence nobody
    stated gets read as certainty.
    """

    field_name: str
    value: str
    evidence: str
    confidence: float
    policy: InferencePolicy = InferencePolicy.PROPOSE

    def __post_init__(self) -> None:
        if not self.field_name.strip():
            raise SetupError("an inferred value needs the field it is for")
        if not self.evidence.strip():
            raise SetupError(
                f"{self.field_name} was inferred with no evidence. An inference "
                f"nobody can check is a guess wearing a better word."
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise SetupError(f"confidence {self.confidence} is not a probability")
        ensure_inferable(self.field_name, self.policy)

    @property
    def state(self) -> ValueState:
        """Where this lands in the projection.

        Derived from the policy rather than stored beside it, so the two cannot
        disagree about whether a value is in use.
        """

        return (
            ValueState.INFERRED
            if self.policy is InferencePolicy.ADOPT_AND_DISCLOSE
            else ValueState.SUGGESTED
        )


@dataclass(frozen=True, slots=True)
class SetupGap:
    """One thing setup is missing, and whether it stops anything.

    `capability` names what is unavailable rather than what is absent, because
    a caller acts on the first. "No publication target" is a fact; "you cannot
    publish, choose a target" is an instruction.
    """

    field_name: str
    capability: str
    blocking: bool
    reason: str
    next_action: str

    def __post_init__(self) -> None:
        if not self.reason.strip() or not self.next_action.strip():
            raise SetupError(
                f"the gap in {self.field_name} must say what is unavailable and "
                f"what to do about it. A gap with neither is a complaint."
            )


@dataclass(frozen=True, slots=True)
class SetupReadiness:
    """What a project's configuration supports, reported apart from its knowledge.

    Never merged with `ReadinessReport`. A project with a clear brief and no
    authorisation is fully understood and cannot publish; one with a working
    connection and one sentence can publish something thin. Averaging those into
    a single number produces a figure that is wrong about both.
    """

    project_id: str
    state: SetupState
    gaps: tuple[SetupGap, ...] = field(default_factory=tuple)
    inferred: tuple[InferredValue, ...] = field(default_factory=tuple)

    @property
    def blocking_gaps(self) -> tuple[SetupGap, ...]:
        return tuple(gap for gap in self.gaps if gap.blocking)

    @property
    def blocks_anything(self) -> bool:
        """Whether setup stops any operation.

        **Knowledge sparsity can never make this true.** Every blocking gap
        must name a capability that is unavailable for one of the five reasons
        N34 allows; a gap that said "not enough is known" would be the rejected
        readiness gate under a new name.
        """

        return bool(self.blocking_gaps)

    def blocks(self, capability: str) -> bool:
        """Whether setup stops one named operation.

        Per capability, because that is how a person acts on it. Expired S3
        credentials must not stop a project generating a document.
        """

        return any(gap.blocking and gap.capability == capability for gap in self.gaps)

    @property
    def disclosures(self) -> tuple[InferredValue, ...]:
        """Inferred values in use, which must travel with what they shaped."""

        return tuple(value for value in self.inferred if value.state in DISCLOSED)
