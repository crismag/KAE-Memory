"""What a caller wants an operation to do, beyond what it is (N40).

A generation policy carries the caller's *intent for this call* — distinct from
`GenerationMode`, which says what the output is for, and from the response
policy, which says how much of the answer to render.

**Deliberately one field.** N42 needs to say whether a submitted observation
should be interpreted, and nothing else needs a policy yet. The alternative was
to invent the whole vocabulary the product context sketches — provisional
inclusion, assumption authority, accepted boundaries, deferred questions — and
inventing a field before its caller exists is how `supersede_older_versions`,
the unreachable qualification, and the assumption service each ended up shipped
and unreachable. Three times is a pattern worth designing against.

What this file does provide is **room**. A policy is a dataclass, so a field can
be added without changing a signature; a value is an enum, so a value can be
added without changing a type. Neither is invented here.

An unrecognised key is **refused, not ignored**. A caller who sends a policy
this version does not understand must not silently receive default behaviour and
believe they configured something.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .errors import DomainInvariantError


class DiscoveryExtraction(StrEnum):
    """Whether a submitted observation is interpreted into candidates.

    `on_submission` is the default because the useful case should not be the
    one a caller has to know to ask for. It costs one model call per
    observation — the same shape ingestion already pays per chunk.

    `disabled` exists for high-volume, telemetry-style observations where
    interpretation is waste. It is an opt-out rather than an opt-in so that the
    ordinary path stays useful without configuration.
    """

    ON_SUBMISSION = "on_submission"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class GenerationPolicy:
    """The caller's intent for one operation.

    Every field carries a default that is the ordinary, useful behaviour, so an
    absent policy and an empty policy mean the same thing — which is what makes
    the parameter optional everywhere without a second code path.
    """

    discovery_extraction: DiscoveryExtraction = DiscoveryExtraction.ON_SUBMISSION

    @property
    def extracts_on_submission(self) -> bool:
        return self.discovery_extraction is DiscoveryExtraction.ON_SUBMISSION

    def as_dict(self) -> dict[str, str]:
        """Render the resolved policy for echoing back.

        A policy that is not echoed is a policy a caller cannot verify they
        set — the same reason the response policy resolves itself into every
        projected payload.
        """

        return {"discovery_extraction": self.discovery_extraction.value}


SUPPORTED_KEYS: frozenset[str] = frozenset({"discovery_extraction"})
"""Every key this version understands.

Named rather than derived from the dataclass fields so that adding a field is a
deliberate two-line change: the field, and its admission here. A field that
appears in one and not the other fails a test rather than half-working.
"""


def from_mapping(policy: Mapping[str, Any] | None) -> GenerationPolicy:
    """Resolve a caller-supplied policy, refusing what this version cannot honour.

    An absent policy resolves to defaults. An unrecognised key raises, because
    accepting one would let a caller believe they had configured behaviour they
    had not — and the failure would show up later as the system ignoring an
    instruction rather than as a rejected request.
    """

    if not policy:
        return GenerationPolicy()

    unknown = sorted(set(policy) - SUPPORTED_KEYS)
    if unknown:
        supported = ", ".join(sorted(SUPPORTED_KEYS))
        raise DomainInvariantError(
            f"unsupported generation policy {unknown}; this version understands: "
            f"{supported}. A policy this version cannot honour is refused rather "
            f"than ignored, so a caller is never told they configured something "
            f"they did not."
        )

    raw = policy.get("discovery_extraction")
    if raw is None:
        return GenerationPolicy()
    try:
        return GenerationPolicy(discovery_extraction=DiscoveryExtraction(str(raw).strip().lower()))
    except ValueError:
        valid = ", ".join(value.value for value in DiscoveryExtraction)
        raise DomainInvariantError(
            f"unknown discovery_extraction {raw!r}; expected one of {valid}"
        ) from None
