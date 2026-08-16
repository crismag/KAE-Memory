"""Place a statement in a discovery area from what it says, not from its kind.

``review_service.unambiguous_area_for`` places a statement only when its kind
leaves no choice, which `SOFTWARE_TEMPLATE` allows for ``actor`` and
``assumption`` alone. Every ``goal``, ``requirement``, ``rule``, ``constraint``
and ``decision`` is therefore left for a person by construction — 692 of 809
items on the AWS Compute Lab ingest, presented as somebody's filing job. That is
`EPI-3`, and doc 17's rule for it is that *"the user should not become
KAE-Memory's taxonomy clerk"*.

**What makes this safe now and did not before.** `ADR-0015` refused offline
guessing on two grounds. The first was readiness inflation, and `EPI-5b` retired
it: a link this module proposes on repository-sourced evidence lifts an area to
``evidenced``, never to ``sufficient``, so no percentage is manufactured. The
second was placing a statement in the wrong area, which is coverage a person
still has to unpick — and that one is retired by grading rather than by
argument. `EXPECTED_AREAS` in the AWS Compute Lab fixture says where 25 statements
belong, written before this module existed, and
``test_placed_statements_land_in_the_area_they_belong_in`` fails if a placement
disagrees.

**The vocabulary is about the areas, not about any project.** Each signal below
is written from what its area *means* in `SOFTWARE_TEMPLATE` — acceptance is
verification, domain is structure and fields, quality is the -ilities — and the
few proper nouns are common infrastructure names rather than terms read off a
corpus. `D-16` is the standing warning: a table tuned on the cases it is scored
against generalises to nothing and reports success anyway.

**Candidates come from the template.** A statement is only ever offered the
areas its kind is already accepted by, so this widens no mapping — `RUN-C1`
rules that redistribution is not the cheap route to a better number. Where a
statement's true area is one its kind cannot reach, this module is wrong and
cannot be otherwise; those cases are `AREA-UNREACHABLE`, a question about the
mapping rather than about the classifier.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from kae_memory.domain.readiness import SOFTWARE_TEMPLATE, ReadinessTemplate


@dataclass(frozen=True, slots=True)
class Placement:
    """One area, how strongly the statement chose it, and why."""

    area_key: str
    confidence: str
    rationale: str


HIGH: Final = "high"
MEDIUM: Final = "medium"
LOW: Final = "low"
"""How much of the placement came from the statement.

``high`` means one area's evidence clearly beat the others, ``medium`` that it
won narrowly, and ``low`` that the statement said nothing discriminating and the
kind's default applied. A consumer that wants only what the text supports reads
``high``; readiness reads all three, because `EPI-5b` already caps what an
auto-placed link can reach.
"""

_STRONG: Final = 4
_CLEAR: Final = 3
_WEAK: Final = 2

_Signal = tuple[str, int, str, str]

_SIGNALS: Final[tuple[_Signal, ...]] = (
    # --- Acceptance criteria: how something is shown to be done ---------------
    # Deliberately *not* "validate". A system that validates a payload is doing
    # its job, not proving it works — "Consumers must parse and validate the
    # message body" is functional behaviour, and treating validation as
    # verification would file every input check under acceptance.
    ("acceptance_criteria", _CLEAR, r"\btests?\b|\btesting\b|\bmocks?\b", "names testing"),
    ("acceptance_criteria", _CLEAR, r"\bverif(y|ied|ication)\b|\bassert", "names verification"),
    # "passes or fails", never a bare "success": a field called
    # success/failure classification is data, not a pass condition.
    (
        "acceptance_criteria",
        _CLEAR,
        r"\b(passes|succeeds) or fails\b|\bmust (pass|fail)\b",
        "states a pass condition",
    ),
    ("acceptance_criteria", _STRONG, r"\bonly after\b.*\bconfirmed\b", "gates on a confirmation"),
    ("acceptance_criteria", _WEAK, r"\bacceptance\b|\bproof\b|\bevidence\b", "names acceptance"),
    # --- Domain model and data: structure, fields, identity ------------------
    ("domain_model_and_data", _CLEAR, r"\bpayloads?\b|\bschemas?\b", "names a data structure"),
    ("domain_model_and_data", _CLEAR, r"\bcontracts?\b|\bmanifest\b", "names a data contract"),
    ("domain_model_and_data", _WEAK, r"\bmessage body\b|\bmetadata\b", "names message content"),
    ("domain_model_and_data", _WEAK, r"uuid|\bcorrelat|\bidentifiers?\b", "names an identity"),
    ("domain_model_and_data", _WEAK, r"\bstateless\b|\bresponsible for\b", "states a model role"),
    # A list of parts is a field list, whatever the fields are called. It has to
    # be a list of *contents* — a verb of containment, or a colon introducing
    # the items — because a list of capabilities is not a record. "CloudWatch
    # must be used for metrics, logs, dashboards, and alarms" enumerates what a
    # service is for; "logs must include messageUuid, transactionUuid, …"
    # enumerates what a record holds.
    (
        "domain_model_and_data",
        _CLEAR,
        r"\b(includes?|contains?|carr(y|ies)|comprise|consists? of)\b[^.]*,[^,]*,|:[^:]*,[^,]*,",
        "enumerates the parts of a record",
    ),
    # --- Functional requirements: what the product does ----------------------
    # A modal followed by a behavioural verb. "must not need to know" does not
    # match, and that is the point: a negated capability is usually a coupling
    # statement, which is a quality attribute.
    (
        "functional_requirements",
        _CLEAR,
        r"\b(must|shall|should)\s+(be able to\s+)?"
        r"(parse|inspect|show|display|answer|list|expose|provide|accept|"
        r"update|notify|trigger|track|allow|enable|exist|support|report)\b",
        "states a behaviour the product performs",
    ),
    # --- Quality attributes: the -ilities ------------------------------------
    (
        "quality_attributes",
        _STRONG,
        r"\bmust not need to know\b|\bdecoupl|\bindependently\b",
        "states decoupling",
    ),
    ("quality_attributes", _CLEAR, r"\breusab|\bremain usable\b", "states reusability"),
    (
        "quality_attributes",
        _CLEAR,
        r"\b(prevent|without)\b[^.]*\b(block|blocking|degrad|affect)",
        "states isolation",
    ),
    (
        "quality_attributes",
        _WEAK,
        r"\bperformance\b|\bavailability\b|\bthroughput\b|\blatency\b|\bresilien",
        "names a quality",
    ),
    # --- Scope and boundaries: what is deliberately not built ----------------
    (
        "scope_and_boundaries",
        _STRONG,
        r"\bnot intended to\b|\bout of scope\b|\bnot in scope\b|\brather than turning\b",
        "states an exclusion",
    ),
    (
        "scope_and_boundaries",
        _STRONG,
        r"\bdistinct\b[^.]*\b(track|module|package|component|subsystem|tree)\b",
        "states a boundary between parts",
    ),
    # --- Constraints and assumptions: the environment KAE does not control ---
    (
        "constraints_and_assumptions",
        _WEAK,
        r"\bnetworks?\b|\bfirewall\b|\bvpn\b|\bproxy\b|\bbandwidth\b",
        "names an environment the project must work within",
    ),
    ("constraints_and_assumptions", _WEAK, r"\bassum|\bwe expect\b", "states an assumption"),
    # --- Interfaces and integrations: systems outside this codebase ----------
    # Common infrastructure names, not corpus terms. Weak on purpose: a
    # statement can name somebody else's service while being about the data it
    # holds, so describing a structure outranks mentioning where it lives.
    (
        "interfaces_and_integrations",
        _WEAK,
        r"\bs3\b|\bcloudwatch\b|\bkafka\b|\bredis\b|\bstripe\b|\bsendgrid\b|\btwilio\b",
        "names a third-party service",
    ),
    (
        "interfaces_and_integrations",
        _WEAK,
        r"\bendpoints?\b|\bwebhooks?\b|\bapis?\b",
        "names an interface",
    ),
    # --- Delivery and operations: getting it running and keeping it so -------
    (
        "delivery_and_operations",
        _WEAK,
        r"\bconfiguration\b|\bdeploy|\brelease\b|\brunbook\b|\bschedules?\b",
        "names delivery or operation",
    ),
    (
        "delivery_and_operations",
        _WEAK,
        r"\.(yaml|yml|toml|ini|env)\b",
        "names a configuration file",
    ),
    # --- Problem and value: why any of it is worth doing ---------------------
    (
        "problem_and_value",
        _CLEAR,
        r"\bso that\b|\bin order to\b|\bthe value\b|\bwithout having to\b",
        "states why it is worth doing",
    ),
)

DEFAULT_AREA_FOR_KIND: Final[dict[str, str]] = {
    "goal": "problem_and_value",
    "requirement": "functional_requirements",
    "rule": "domain_model_and_data",
    "constraint": "constraints_and_assumptions",
    "decision": "scope_and_boundaries",
}
"""Where a statement of each kind goes when it says nothing discriminating.

Not a tie-breaker of convenience: each is the area the kind is *about* when
nothing narrows it. A requirement that names no quality, no field and no outside
system is a statement about what the product does; a constraint that names no
boundary and no environment is still a constraint. Placing it there and marking
the placement ``low`` is more honest than abstaining, because abstaining is what
put 692 rows in front of a person.

Kinds absent from this map are placed only when a signal fires — ``actor`` and
``assumption`` never reach here, since exactly one area accepts them.
"""


def areas_accepting(kind: str, template: ReadinessTemplate = SOFTWARE_TEMPLATE) -> tuple[str, ...]:
    """Return the areas whose definition already accepts ``kind``."""

    return tuple(
        area.key for area in template.areas if any(member.value == kind for member in area.kinds)
    )


def areas_named_by(text: str, template: ReadinessTemplate = SOFTWARE_TEMPLATE) -> tuple[str, ...]:
    """The areas ``text`` names most strongly, scored over the whole template.

    A different question from `classify_by_content`, which asks *where does this
    sentence file* and therefore only ever offers the areas the statement's kind
    is already accepted by. `SYN-5a` asks *what does this role own*, and exactly
    one area accepts an ``actor`` — so restricting the candidates would make
    every project role responsible for ``users_and_stakeholders``, which is the
    flattening doc 03 exists to remove.

    Returns every area tied at the top score, and empty where nothing fired. No
    default is applied: a caller asking what somebody owns must be able to tell
    *this names nothing* from *this names one thing*, and
    `DEFAULT_AREA_FOR_KIND` would answer the first as if it were the second.
    """

    lowered = text.casefold()
    scores = dict.fromkeys((area.key for area in template.areas), 0)
    for area, weight, pattern, _ in _SIGNALS:
        if area in scores and re.search(pattern, lowered):
            scores[area] += weight

    best = max(scores.values())
    if best == 0:
        return ()
    return tuple(sorted(area for area, score in scores.items() if score == best))


def classify_by_content(
    kind: str, text: str, template: ReadinessTemplate = SOFTWARE_TEMPLATE
) -> Placement | None:
    """Return where ``text`` belongs, or ``None`` if its kind reaches no area.

    ``None`` means the template offers nothing — ``unknown`` accepts no area at
    all, and an open question is not knowledge about a discovery area however it
    is worded. It never means *this was too hard*: a kind with candidates always
    gets one, at the confidence the statement earned.
    """

    candidates = areas_accepting(kind, template)
    if not candidates:
        return None
    if len(candidates) == 1:
        return Placement(candidates[0], HIGH, f"only {candidates[0]} accepts a {kind}")

    lowered = text.casefold()
    scores = dict.fromkeys(candidates, 0)
    reasons: dict[str, list[str]] = {area: [] for area in candidates}
    for area, weight, pattern, why in _SIGNALS:
        if area in scores and re.search(pattern, lowered):
            scores[area] += weight
            reasons[area].append(why)

    best = max(scores, key=lambda area: (scores[area], area))
    runner_up = max((scores[area] for area in scores if area != best), default=0)
    default = DEFAULT_AREA_FOR_KIND.get(kind)

    if scores[best] == 0 or (scores[best] == runner_up and default in candidates):
        assert default is not None, f"no default area for kind {kind!r} with several candidates"
        return Placement(
            default,
            LOW,
            f"nothing in the statement chose between {len(candidates)} areas a {kind} "
            f"can reach, so it went where a {kind} goes by default",
        )

    why = ", ".join(dict.fromkeys(reasons[best]))
    confidence = HIGH if scores[best] - runner_up >= _WEAK else MEDIUM
    return Placement(best, confidence, why)


def classify_corpus(
    statements: Sequence[tuple[str, str]], template: ReadinessTemplate = SOFTWARE_TEMPLATE
) -> tuple[Placement | None, ...]:
    """Classify ``(kind, text)`` pairs — the shape a caller holding items has."""

    return tuple(classify_by_content(kind, text, template) for kind, text in statements)


__all__ = [
    "DEFAULT_AREA_FOR_KIND",
    "HIGH",
    "LOW",
    "MEDIUM",
    "Placement",
    "areas_accepting",
    "classify_by_content",
    "classify_corpus",
]
