"""Rule synthesis — a rule's authority is its source's, never its wording.

`04-RULES-CONTROLS.md` makes two claims that decide this module, and they pull
in opposite directions.

## Authority comes from where the rule came from

    A user preference, product decision, architecture consequence, security
    policy, law/regulation, and KAE recommendation must not appear as
    equivalent `rule v1` records.

So authority is a property of the **origin**, and `authority_of` is the only
thing that assigns it. *Must never* is the grammar of the sentence somebody
wrote down — the reading `D-125` gave *"we decided to use PostgreSQL"* and
`D-129` gave *shall*, a third time. A preference worded as an absolute stays a
preference.

## Being derived is not a reason to ask a person anything

    Safe derived rules need not create another approval task merely because
    they were derived.

A rule implied by an accepted decision is active on the strength of that
acceptance. Asking for confirmation a second time is asking a person to
re-confirm the decision they already made, which is the review queue arriving
through a new door.

## Which makes the acceptance of the source the whole boundary

A rule derived from something nobody accepted is **not** active: deriving from a
proposal would launder a proposal into a control (`D-126`). It is computed,
reported by name, and applied to nothing.

## Enforceable control versus descriptive policy is derived

Doc 04 asks the two to be distinguished. A rule is a control when a mechanism —
a CI check, a permission, a gate — is named *for* it, and mechanisms arrive as
evidence. Manufacturing one would make every rule enforceable by the act of
synthesising it, which is `D-131`'s refusal in the same shape.

Nothing here raises attention. The gap this layer can honestly report is a rule
whose authority nobody attributed; ranking gaps by what they block is `SYN-11`.

Everything here is pure. Storage, the run and any surface live above.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from kae_memory.domain.area_classification import areas_named_by


class RuleFamily(StrEnum):
    """Doc 04's families, as the twelve it lists.

    A family is what a rule is *about*. It carries no weight: an engineering
    standard and a law are different families and different authorities, and the
    two facts are independent.
    """

    BUSINESS = "business"
    FUNCTIONAL = "functional"
    WORKFLOW = "workflow"
    ARCHITECTURE = "architecture"
    ENGINEERING_STANDARD = "engineering_standard"
    MODULE = "module"
    AUTHORITY_SECURITY = "authority_security"
    LEGAL = "legal"
    GOVERNANCE = "governance"
    DATA_LIFECYCLE = "data_lifecycle"
    OPERATIONAL = "operational"
    QUALITY = "quality"


class RuleOrigin(StrEnum):
    """Doc 04's eight sources, plus the case where nobody said.

    ``UNATTRIBUTED`` is not a ninth source. It is the absence of one, kept as a
    value so the gap can be reported by name rather than guessed at.
    """

    REQUIREMENT_SPECIFICATION = "requirement_specification"
    BUSINESS_POLICY = "business_policy"
    WORKFLOW_STATE_MACHINE = "workflow_state_machine"
    ARCHITECTURE_DECISION = "architecture_decision"
    ENGINEERING_STANDARD = "engineering_standard"
    MODULE_CONTRACT = "module_contract"
    LAW_OR_SECURITY_AUTHORITY = "law_or_security_authority"
    CONTROL_MECHANISM = "control_mechanism"
    UNATTRIBUTED = "unattributed"


class RuleAuthority(StrEnum):
    """What the rule can overrule, ordered by weight.

    Doc 04's *"must not appear as equivalent"* list, as the thing that makes two
    `rule v1` rows unequal.
    """

    LAW = "law"
    SECURITY_POLICY = "security_policy"
    PRODUCT_DECISION = "product_decision"
    ARCHITECTURE_CONSEQUENCE = "architecture_consequence"
    ENGINEERING_STANDARD = "engineering_standard"
    USER_PREFERENCE = "user_preference"
    UNATTRIBUTED = "unattributed"


#: The whole of the authority model: origin decides, wording never does.
_AUTHORITY_OF_ORIGIN: Final[dict[RuleOrigin, RuleAuthority]] = {
    RuleOrigin.LAW_OR_SECURITY_AUTHORITY: RuleAuthority.LAW,
    RuleOrigin.CONTROL_MECHANISM: RuleAuthority.SECURITY_POLICY,
    RuleOrigin.REQUIREMENT_SPECIFICATION: RuleAuthority.PRODUCT_DECISION,
    RuleOrigin.BUSINESS_POLICY: RuleAuthority.PRODUCT_DECISION,
    RuleOrigin.ARCHITECTURE_DECISION: RuleAuthority.ARCHITECTURE_CONSEQUENCE,
    RuleOrigin.MODULE_CONTRACT: RuleAuthority.ARCHITECTURE_CONSEQUENCE,
    RuleOrigin.WORKFLOW_STATE_MACHINE: RuleAuthority.ARCHITECTURE_CONSEQUENCE,
    RuleOrigin.ENGINEERING_STANDARD: RuleAuthority.ENGINEERING_STANDARD,
    RuleOrigin.UNATTRIBUTED: RuleAuthority.UNATTRIBUTED,
}

_LEGAL: Final = re.compile(
    r"\b(gdpr|hipaa|sox|pci[- ]dss|ccpa|regulat\w*|statut\w*|"
    r"lawful|legally|jurisdiction|data protection act)\b",
    re.IGNORECASE,
)

_AUTHORITY_SECURITY: Final = re.compile(
    r"\b(permission\w*|authenticat\w*|authoris\w*|authoriz\w*|credential\w*|"
    r"secret\w*|least privilege|access control|rbac|token\w*|encrypt\w*)\b",
    re.IGNORECASE,
)

_GOVERNANCE: Final = re.compile(
    r"\b(governance|steering|sign[- ]?off|approval board|escalat\w*|"
    r"model card|responsible ai|ethics|audit trail)\b",
    re.IGNORECASE,
)

_DATA_LIFECYCLE: Final = re.compile(
    r"\b(retention|retain\w*|purge[sd]?|archiv\w*|backup\w*|"
    r"personal data|pii|anonymis\w*|anonymiz\w*|soft[- ]delete\w*)\b",
    re.IGNORECASE,
)

_OPERATIONAL: Final = re.compile(
    r"\b(deploy\w*|rollback\w*|release\w*|on[- ]call|incident\w*|"
    r"runbook\w*|monitor\w*|alert\w*|uptime|sla)\b",
    re.IGNORECASE,
)

_QUALITY: Final = re.compile(
    r"\b(test\w*|coverage|lint\w*|type[- ]check\w*|ci\b|pipeline|"
    r"regression\w*|review before merge|definition of done)\b",
    re.IGNORECASE,
)

_ARCHITECTURE: Final = re.compile(
    r"\b(layer\w*|dependenc\w*|boundar\w*|adapter\w*|domain (?:layer|module)|"
    r"must not import|coupl\w*|hexagonal|port\b|schema migration)\b",
    re.IGNORECASE,
)

_ENGINEERING_STANDARD: Final = re.compile(
    r"\b(naming|style|format\w*|docstring\w*|convention\w*|"
    r"line length|commit message|branch name)\b",
    re.IGNORECASE,
)

_MODULE: Final = re.compile(
    r"\b(module|component|package|service) (?:must|shall|owns?|is responsible)\b",
    re.IGNORECASE,
)

_WORKFLOW: Final = re.compile(
    r"\b(state|status|transition\w*|before (?:it|they) can|"
    r"only after|moves? (?:to|from)|workflow|step \d)\b",
    re.IGNORECASE,
)

_BUSINESS: Final = re.compile(
    r"\b(customer\w*|price|pricing|billing|invoice\w*|discount\w*|"
    r"tier\w*|quota\w*|contract\w*|subscription\w*)\b",
    re.IGNORECASE,
)

#: Ordered most specific first, for `requirements.py`'s reason: these overlap by
#: construction and the order states which reading governs. Legal and security
#: lead because a sentence that mentions either is about that first.
_FAMILY_ORDER: Final = (
    (_LEGAL, RuleFamily.LEGAL),
    (_AUTHORITY_SECURITY, RuleFamily.AUTHORITY_SECURITY),
    (_GOVERNANCE, RuleFamily.GOVERNANCE),
    (_DATA_LIFECYCLE, RuleFamily.DATA_LIFECYCLE),
    (_OPERATIONAL, RuleFamily.OPERATIONAL),
    (_QUALITY, RuleFamily.QUALITY),
    (_MODULE, RuleFamily.MODULE),
    (_ARCHITECTURE, RuleFamily.ARCHITECTURE),
    (_ENGINEERING_STANDARD, RuleFamily.ENGINEERING_STANDARD),
    (_WORKFLOW, RuleFamily.WORKFLOW),
    (_BUSINESS, RuleFamily.BUSINESS),
)


def authority_of(origin: RuleOrigin) -> RuleAuthority:
    """What the rule can overrule, from where it came from.

    Takes no statement, deliberately. A function that could read the wording
    would eventually be asked to, and *must never* in a preference is still a
    preference.
    """

    return _AUTHORITY_OF_ORIGIN[origin]


def family_of(statement: str) -> RuleFamily:
    """What the rule is about.

    Defaults to ``FUNCTIONAL``: doc 04's families are a partition of rules that
    already are rules, so an unrecognised one is a rule about what the product
    does rather than a rule about nothing.
    """

    for pattern, family in _FAMILY_ORDER:
        if pattern.search(statement):
            return family
    return RuleFamily.FUNCTIONAL


@dataclass(frozen=True, slots=True)
class RuleCandidate:
    """One rule-shaped statement, before anything decides what it weighs."""

    members: tuple[str, ...]
    """Opaque member keys — the caller's knowledge item ids, as strings."""

    canonical_key: str
    statement: str
    origin: RuleOrigin = RuleOrigin.UNATTRIBUTED
    source_accepted: bool = False
    """Whether the thing it was derived from was accepted. The whole boundary."""

    enforcement_mechanisms: tuple[str, ...] = field(default_factory=tuple)
    """Mechanisms named for this rule. Evidence — KAE writes none (`D-132`)."""


@dataclass(frozen=True, slots=True)
class PlannedRule:
    """One rule as the model would hold it."""

    candidate: RuleCandidate
    family: RuleFamily
    authority: RuleAuthority
    capability_areas: tuple[str, ...]

    @property
    def active(self) -> bool:
        """Whether the rule governs anything.

        Derivation is not the question — acceptance of the source is. A derived
        rule from an accepted source is active without asking again, and a rule
        from an unaccepted one is not active however it is worded.
        """

        return self.candidate.source_accepted

    @property
    def enforceable(self) -> bool:
        """A control rather than descriptive policy.

        True only when a mechanism arrived with it. Derived, not stored, for
        `D-125`'s reason.
        """

        return bool(self.candidate.enforcement_mechanisms)

    @property
    def attributed(self) -> bool:
        return self.authority is not RuleAuthority.UNATTRIBUTED


@dataclass(frozen=True, slots=True)
class RuleModelPlan:
    """What a rule synthesis run would write, before it writes anything."""

    rules: tuple[PlannedRule, ...]

    @property
    def active(self) -> tuple[PlannedRule, ...]:
        return tuple(one for one in self.rules if one.active)

    @property
    def inert(self) -> tuple[PlannedRule, ...]:
        """Computed from something nobody accepted, so applied to nothing."""

        return tuple(one for one in self.rules if not one.active)

    @property
    def controls(self) -> tuple[PlannedRule, ...]:
        """Doc 04's *active controls* — enforceable and actually governing."""

        return tuple(one for one in self.rules if one.active and one.enforceable)

    @property
    def unattributed(self) -> tuple[PlannedRule, ...]:
        """The gap this layer can honestly report: nobody said where it came from."""

        return tuple(one for one in self.rules if not one.attributed)

    @property
    def families(self) -> tuple[RuleFamily, ...]:
        """The families present among active rules, in doc 04's declared order."""

        present = {one.family for one in self.active}
        return tuple(family for family in RuleFamily if family in present)


def plan_rule_model(candidates: Sequence[RuleCandidate]) -> RuleModelPlan:
    """Turn rule-shaped evidence into a rule model.

    Every candidate becomes a rule. Nothing is dropped and nothing is queued:
    a rule that cannot govern is reported inert, and a rule whose origin nobody
    gave is reported unattributed.
    """

    return RuleModelPlan(
        rules=tuple(
            PlannedRule(
                candidate=candidate,
                family=family_of(candidate.statement),
                authority=authority_of(candidate.origin),
                capability_areas=areas_named_by(candidate.statement),
            )
            for candidate in candidates
        )
    )
