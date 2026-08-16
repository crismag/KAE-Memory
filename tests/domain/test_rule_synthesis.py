"""Rule synthesis: authority is the source's, and derivation asks nobody anything.

Pure domain (`SYN-5c`, doc 04, `D-132`). The corpus's own fifteen rule
statements are used verbatim, because doc 04's *"must not appear as equivalent
`rule v1` records"* is a complaint about *these* rows and a fixture written to
pass would prove nothing.
"""

from __future__ import annotations

from tests.synthesis.corpus import OBSERVATIONS, ExtractedObservation

from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.synthesizers.rules import (
    RuleAuthority,
    RuleCandidate,
    RuleFamily,
    RuleModelPlan,
    RuleOrigin,
    authority_of,
    family_of,
    plan_rule_model,
)


def _corpus_rules() -> tuple[ExtractedObservation, ...]:
    return tuple(one for one in OBSERVATIONS if one.kind is KnowledgeKind.RULE)


def _candidate(
    statement: str,
    *,
    origin: RuleOrigin = RuleOrigin.UNATTRIBUTED,
    accepted: bool = False,
    mechanisms: tuple[str, ...] = (),
) -> RuleCandidate:
    return RuleCandidate(
        members=("item-1",),
        canonical_key=statement.lower()[:60],
        statement=statement,
        origin=origin,
        source_accepted=accepted,
        enforcement_mechanisms=mechanisms,
    )


class TestAuthorityComesFromTheSourceAndNeverFromTheWording:
    def test_a_preference_worded_as_an_absolute_is_still_a_preference(self) -> None:
        shouted = _candidate(
            "The system must never use tabs for indentation, under any circumstances.",
            origin=RuleOrigin.UNATTRIBUTED,
        )
        plan = plan_rule_model([shouted])

        assert plan.rules[0].authority is RuleAuthority.UNATTRIBUTED

    def test_a_law_worded_mildly_still_outranks_a_shouted_standard(self) -> None:
        law = _candidate(
            "We generally try to honour GDPR erasure requests.",
            origin=RuleOrigin.LAW_OR_SECURITY_AUTHORITY,
        )
        standard = _candidate(
            "Naming conventions MUST ALWAYS be followed without exception.",
            origin=RuleOrigin.ENGINEERING_STANDARD,
        )
        plan = plan_rule_model([law, standard])

        assert plan.rules[0].authority is RuleAuthority.LAW
        assert plan.rules[1].authority is RuleAuthority.ENGINEERING_STANDARD

    def test_authority_is_a_function_of_origin_alone(self) -> None:
        for origin in RuleOrigin:
            assert authority_of(origin) is authority_of(origin)

        assert authority_of(RuleOrigin.ARCHITECTURE_DECISION) is (
            RuleAuthority.ARCHITECTURE_CONSEQUENCE
        )
        assert authority_of(RuleOrigin.BUSINESS_POLICY) is RuleAuthority.PRODUCT_DECISION

    def test_the_six_kinds_doc_04_names_do_not_collapse_into_one(self) -> None:
        origins = (
            RuleOrigin.LAW_OR_SECURITY_AUTHORITY,
            RuleOrigin.CONTROL_MECHANISM,
            RuleOrigin.BUSINESS_POLICY,
            RuleOrigin.ARCHITECTURE_DECISION,
            RuleOrigin.ENGINEERING_STANDARD,
            RuleOrigin.UNATTRIBUTED,
        )
        assert len({authority_of(origin) for origin in origins}) == len(origins)


class TestBeingDerivedIsNotAReasonToAskAnybodyAnything:
    def test_a_rule_derived_from_an_accepted_source_is_active_without_asking_again(
        self,
    ) -> None:
        derived = _candidate(
            "Adapters must not import the domain layer directly.",
            origin=RuleOrigin.ARCHITECTURE_DECISION,
            accepted=True,
        )
        plan = plan_rule_model([derived])

        assert plan.active == plan.rules
        assert plan.inert == ()

    def test_a_rule_derived_from_something_nobody_accepted_governs_nothing(self) -> None:
        proposed = _candidate(
            "Every module must publish a versioned contract.",
            origin=RuleOrigin.MODULE_CONTRACT,
            accepted=False,
        )
        plan = plan_rule_model([proposed])

        assert plan.active == ()
        assert plan.inert == plan.rules

    def test_an_unaccepted_source_is_reported_rather_than_dropped(self) -> None:
        plan = plan_rule_model(
            [
                _candidate("Secrets must be rotated quarterly.", accepted=False),
                _candidate(
                    "Deployments roll back automatically on error budget burn.",
                    origin=RuleOrigin.CONTROL_MECHANISM,
                    accepted=True,
                ),
            ]
        )

        assert len(plan.rules) == 2
        assert len(plan.inert) == 1
        assert len(plan.active) == 1


class TestKaeWritesNoEnforcementMechanism:
    def test_a_rule_without_a_named_mechanism_is_descriptive_policy(self) -> None:
        plan = plan_rule_model(
            [
                _candidate(
                    "Code must be reviewed before merge.",
                    origin=RuleOrigin.ENGINEERING_STANDARD,
                    accepted=True,
                )
            ]
        )

        assert plan.rules[0].enforceable is False
        assert plan.controls == ()

    def test_a_mechanism_that_arrived_as_evidence_makes_it_a_control(self) -> None:
        plan = plan_rule_model(
            [
                _candidate(
                    "Code must be reviewed before merge.",
                    origin=RuleOrigin.ENGINEERING_STANDARD,
                    accepted=True,
                    mechanisms=("github branch protection",),
                )
            ]
        )

        assert plan.rules[0].enforceable is True
        assert plan.controls == plan.rules

    def test_an_enforceable_rule_from_an_unaccepted_source_is_not_an_active_control(
        self,
    ) -> None:
        plan = plan_rule_model(
            [
                _candidate(
                    "Personal data is purged after ninety days.",
                    origin=RuleOrigin.LAW_OR_SECURITY_AUTHORITY,
                    accepted=False,
                    mechanisms=("retention job",),
                )
            ]
        )

        assert plan.rules[0].enforceable is True
        assert plan.controls == ()


class TestFamiliesSeparateWhatARuleIsAboutFromWhatItWeighs:
    def test_doc_04_families_are_recognised(self) -> None:
        assert family_of("GDPR erasure requests are honoured within 30 days.") is (RuleFamily.LEGAL)
        assert family_of("Access control follows least privilege.") is (
            RuleFamily.AUTHORITY_SECURITY
        )
        assert family_of("Personal data retention is capped at ninety days.") is (
            RuleFamily.DATA_LIFECYCLE
        )
        assert family_of("Every deploy must be reversible by rollback.") is (RuleFamily.OPERATIONAL)
        assert family_of("Coverage must not drop below the recorded threshold in CI.") is (
            RuleFamily.QUALITY
        )

    def test_an_unrecognised_rule_is_functional_rather_than_nothing(self) -> None:
        assert family_of("Totals are shown to two decimal places.") is RuleFamily.FUNCTIONAL

    def test_family_and_authority_are_independent(self) -> None:
        preference = _candidate(
            "Personal data retention is capped at ninety days.",
            origin=RuleOrigin.UNATTRIBUTED,
        )
        law = _candidate(
            "Personal data retention is capped at ninety days.",
            origin=RuleOrigin.LAW_OR_SECURITY_AUTHORITY,
        )
        plan = plan_rule_model([preference, law])

        assert plan.rules[0].family is plan.rules[1].family
        assert plan.rules[0].authority is not plan.rules[1].authority

    def test_families_are_counted_over_active_rules_only(self) -> None:
        plan = plan_rule_model(
            [
                _candidate(
                    "Access control follows least privilege.",
                    origin=RuleOrigin.LAW_OR_SECURITY_AUTHORITY,
                    accepted=True,
                ),
                _candidate(
                    "Every deploy must be reversible by rollback.",
                    origin=RuleOrigin.CONTROL_MECHANISM,
                    accepted=False,
                ),
            ]
        )

        assert plan.families == (RuleFamily.AUTHORITY_SECURITY,)


class TestNothingHereRaisesAttention:
    def test_an_unattributed_rule_is_reported_by_name_not_queued(self) -> None:
        plan = plan_rule_model(
            [
                _candidate("Nobody said where this came from.", accepted=True),
                _candidate(
                    "Adapters must not import the domain layer directly.",
                    origin=RuleOrigin.ARCHITECTURE_DECISION,
                    accepted=True,
                ),
            ]
        )

        assert len(plan.unattributed) == 1
        assert plan.unattributed[0].candidate.statement.startswith("Nobody said")
        assert not hasattr(plan, "attention")

    def test_an_unattributed_rule_from_an_accepted_source_still_governs(self) -> None:
        plan = plan_rule_model([_candidate("Nobody said where this came from.", accepted=True)])

        assert plan.active == plan.rules

    def test_every_candidate_becomes_a_rule_and_nothing_is_dropped(self) -> None:
        candidates = [
            _candidate("Totals are shown to two decimal places."),
            _candidate("GDPR erasure is honoured.", origin=RuleOrigin.LAW_OR_SECURITY_AUTHORITY),
            _candidate("Deploys roll back.", origin=RuleOrigin.CONTROL_MECHANISM, accepted=True),
        ]
        plan = plan_rule_model(candidates)

        assert len(plan.rules) == len(candidates)
        assert [one.candidate for one in plan.rules] == candidates

    def test_an_empty_corpus_is_an_empty_model(self) -> None:
        plan = plan_rule_model([])

        assert plan.rules == ()
        assert plan.active == ()
        assert plan.controls == ()
        assert plan.families == ()


class TestTheGoldenCorpusPinned:
    """The measurement, so a later change to the lexicon has to argue with it."""

    def _plan(self) -> RuleModelPlan:
        return plan_rule_model([_candidate(one.content) for one in _corpus_rules()])

    def test_fifteen_rule_rows_stay_fifteen_rules(self) -> None:
        plan = self._plan()

        assert len(plan.rules) == 15

    def test_every_corpus_rule_is_unattributed_and_therefore_governs_nothing(self) -> None:
        """The corpus records rules and never records where they came from.

        Which is the pathology doc 04 opens with, measured: fifteen rows that
        look interchangeable because the one thing distinguishing them was
        never captured. The layer reports all fifteen by name and applies none
        of them — the same shape `SYN-5e` found, where the corpus confirms no
        constraint and so stores no effect.
        """

        plan = self._plan()

        assert len(plan.unattributed) == 15
        assert plan.active == ()
        assert plan.inert == plan.rules
        assert plan.controls == ()
        assert plan.families == ()

    def test_no_corpus_rule_is_enforceable_because_none_names_a_mechanism(self) -> None:
        """Asserted apart from ``controls``, which every corpus rule fails for
        the *other* reason — being inert. A layer that manufactured a mechanism
        from *must* would still report no controls here, and the refusal that
        matters would go unmeasured.
        """

        plan = self._plan()

        assert [one for one in plan.rules if one.enforceable] == []

    def test_the_family_read_reaches_two_of_fifteen_and_the_rest_are_functional(self) -> None:
        """Pinned as a floor, not tuned to a fraction (`D-16`).

        *"Memory must not become a blob warehouse"* is an architecture rule to
        a reader and matches no architecture term; *"Acquisition stays in
        Studio"* names a module boundary without naming a module. Widening the
        lexicon until these fifteen rows sort correctly is reading terms off
        the fixture, and the family is the axis that carries no weight anyway —
        authority is what makes two rows unequal, and it comes from the origin.
        """

        plan = self._plan()
        families = [one.family for one in plan.rules]

        assert families.count(RuleFamily.FUNCTIONAL) == 13
        assert families.count(RuleFamily.AUTHORITY_SECURITY) == 1
        assert families.count(RuleFamily.QUALITY) == 1

    def test_the_capability_axis_reaches_two_of_fifteen(self) -> None:
        plan = self._plan()

        assert sum(1 for one in plan.rules if one.capability_areas) == 2
