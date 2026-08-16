"""How a row came to be known, which is not how it participates in reasoning.

`EPI-1`, doc 17, `D-134`. Doc 17 names eight classes an observation must be able
to carry — observed, derived, proposed, assumed, accepted, conflicting,
superseded, noise — and the checklist row says the overlap with `EvidenceRole`
must be reconciled rather than duplicated. Reconciling it splits the eight in
two.

Five of them answer **how KAE came to know this**. That is a property of the
row's origin: it is settled when the row is written and no rerun changes it.
Those five are here.

Three of them — conflicting, superseded, noise — answer **how this row
participates in reasoning now**. That is a property of the current evidence
graph, it changes every time reconciliation runs, and it is already
`EvidenceRole`. Repeating any of them here would store a second copy of a
derived state, free to disagree with the first the moment either is recomputed
(`D-125`). ``test_no_member_collides_with_an_evidence_role`` is what stops that
being reintroduced quietly.

**Nothing here reads a statement.** `classify` takes a kind, a lifecycle and the
source types on the row's producing links, and deliberately takes no text — the
same refusal as `D-129`, `D-131` and `D-132`, except that here the signature is
the guard rather than a test.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .lifecycle import LifecycleState
from .models import KnowledgeKind, KnowledgeSourceType


class EpistemicClass(StrEnum):
    """How KAE came to know one statement.

    Wire values are deliberately disjoint from `EvidenceRole`'s, because the two
    are read side by side and a shared word would invite one to be passed where
    the other is meant.
    """

    OBSERVED = "observed"
    """A source contains or demonstrates the statement.

    Doc 17 is careful that this does not mean the statement is current project
    intent — only that the evidence exists.
    """

    DERIVED = "derived"
    """KAE inferred it from knowledge it already held, with no source of its own."""

    PROPOSED = "proposed"
    """KAE recommends a change that evidence and authority do not already carry.

    **Unreachable from acquisition, and that is the finding.** Nothing on the
    ingest path recommends anything; a proposal is what synthesis produces, and
    what synthesis produces is a synthesized object rather than an observation.
    The member exists so the distinction doc 17 draws is not lost, and
    ``test_nothing_acquired_is_ever_a_proposal`` pins that no subject reaches
    it — so if acquisition ever does propose something, a guard says so instead
    of the class quietly appearing in a distribution.
    """

    ASSUMED = "assumed"
    """A provisional belief held to allow progress while evidence is short."""

    ACCEPTED = "accepted"
    """Settled by an authority, which for a knowledge item is a validation."""

    UNDETERMINED = "undetermined"
    """No producing link names a source, so there is nothing to read this from.

    Not a synonym for observed. `EPI-5b` already ruled that provenance which
    says nothing grounds nothing, and the live database still holds 4,136 links
    with a ``NULL`` source type — a default of observed would promote every one
    of them by omission.
    """


ACQUIRABLE: frozenset[EpistemicClass] = frozenset(
    {
        EpistemicClass.OBSERVED,
        EpistemicClass.DERIVED,
        EpistemicClass.ASSUMED,
        EpistemicClass.ACCEPTED,
        EpistemicClass.UNDETERMINED,
    }
)
"""The classes an acquired row can hold. `PROPOSED` is the one that cannot."""


GROUNDED: frozenset[EpistemicClass] = frozenset({EpistemicClass.OBSERVED, EpistemicClass.ACCEPTED})
"""Classes that rest on something outside KAE.

Derived and assumed rest on KAE's own reasoning; undetermined rests on nothing
that has been recorded. Kept as a named set so a caller asking *is this
externally grounded* does not re-derive the answer from a tuple of members.
"""


@dataclass(frozen=True, slots=True)
class EpistemicSubject:
    """Everything `classify` is allowed to see about one row.

    There is no statement field, and that omission is the point: authority and
    epistemic standing come from where a row came from, never from how it is
    worded. Adding text here would be the first step of the mistake `D-129`
    named.
    """

    kind: KnowledgeKind
    lifecycle: LifecycleState
    source_types: frozenset[KnowledgeSourceType] = frozenset()


def classify(subject: EpistemicSubject) -> EpistemicClass:
    """Read one row's epistemic class off its origin and its acceptance.

    The order is the decision, not an implementation accident (`D-134`):

    1. a validated row is **accepted** — a person settled it, and that is an act
       rather than a phrasing, so it outranks wherever the row came from;
    2. an assumption is **assumed** ahead of its source, because an assumption
       is provisional whoever first wrote it. Doc 17's *"PostgreSQL is intended
       for production"* is precisely a KAE inference that is an assumption;
    3. no producing source type at all is **undetermined**;
    4. `KAE_INFERENCE` and nothing else is **derived**;
    5. anything else is **observed**.

    Step 4 is why grounding beats inference on a row carrying both.
    `KnowledgeSourceType` already rules that only a statement KAE derived from
    knowledge it already held is an inference, and that collapsing the two would
    make every extraction a proposal. A row with a repository link has evidence,
    whatever else it also has.
    """

    if subject.lifecycle is LifecycleState.VALIDATED:
        return EpistemicClass.ACCEPTED
    if subject.kind is KnowledgeKind.ASSUMPTION:
        return EpistemicClass.ASSUMED
    if not subject.source_types:
        return EpistemicClass.UNDETERMINED
    if subject.source_types == {KnowledgeSourceType.KAE_INFERENCE}:
        return EpistemicClass.DERIVED
    return EpistemicClass.OBSERVED


def classify_all(subjects: Iterable[EpistemicSubject]) -> tuple[EpistemicClass, ...]:
    """`classify` over many rows, in the order given."""

    return tuple(classify(subject) for subject in subjects)
