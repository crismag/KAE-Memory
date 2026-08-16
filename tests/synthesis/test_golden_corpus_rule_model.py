"""Golden corpus: fifteen rules, and not one of them says where it came from.

`SYN-5c`, doc 04, `D-132`/`D-133`. The domain layer is tested in
`tests/domain/test_rule_synthesis.py`; this is what the run persists, and what
it refuses to persist.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, SynthesisService, WriteKnowledgeRequest
from kae_memory.application.rule_synthesis_service import RuleSynthesisService
from kae_memory.domain.errors import KnowledgeNotFoundError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind, Project
from kae_memory.domain.synthesis import SynthesizedLifecycle
from kae_memory.domain.synthesizers.rules import RuleAuthority, RuleOrigin
from tests.synthesis.corpus import count_by_kind
from tests.synthesis.load import load_golden_corpus

SECRETS_RULE = "Credentials must never be written to a log."
CI_CHECK = "The secret-scanning check in CI"


def _services(
    factory: sessionmaker[Session],
) -> tuple[MemoryService, RuleSynthesisService, SynthesisService, Project]:
    memory = MemoryService(factory)
    project = memory.create_project("KAE synthesis corpus", key="golden-rules")
    return memory, RuleSynthesisService(factory), SynthesisService(factory), project


def _rule(memory: MemoryService, project: Project, statement: str) -> None:
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "rule-attribution")
    memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind=KnowledgeKind.RULE.value, content=statement, source="fixture")],
        output_summary={"fixture": "rule-attribution"},
    )


class TestEveryRuleBecomesAnObject:
    def test_each_rule_observation_becomes_exactly_one_object(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, rules, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = rules.synthesize(project.id)

        expected = count_by_kind()[KnowledgeKind.RULE.value]
        assert report.considered == expected
        assert len(report.rules) == expected
        stored = synthesis.list_objects(project.id, KnowledgeKind.RULE.value)
        assert len(stored) == expected
        assert {obj.lifecycle for obj in stored} == {SynthesizedLifecycle.WORKING}

    def test_the_corpus_reading_is_pinned(self, factory: sessionmaker[Session]) -> None:
        """`D-132`'s measurement: the corpus records rules and never records
        where any of them came from, which is doc 04's opening complaint."""

        memory, rules, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = rules.synthesize(project.id)

        assert len(report.unattributed) == 15
        assert report.active == 0
        assert report.controls == 0
        assert report.families == ()


class TestKaeAttributesNothingAndNamesNoMechanism:
    def test_the_run_stores_no_attribution_and_no_mechanism(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`D-132`, and the two guards the row exists for: an origin KAE
        attributed would make the rule active, and a mechanism KAE named would
        make it a control, by the act of synthesising it."""

        memory, rules, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        rules.synthesize(project.id)

        assert rules.list_attributions(project.id) == ()
        assert rules.list_mechanisms(project.id) == ()

    def test_so_every_rule_is_unattributed_and_inert(self, factory: sessionmaker[Session]) -> None:
        memory, rules, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = rules.synthesize(project.id)

        assert all(one.authority is RuleAuthority.UNATTRIBUTED for one in report.rules)
        assert all(one.origin is RuleOrigin.UNATTRIBUTED for one in report.rules)
        assert not any(one.active or one.enforceable for one in report.rules)

    def test_nothing_reaches_the_attention_queue(self, factory: sessionmaker[Session]) -> None:
        """An unattributed rule is a gap in the record, not an interruption."""

        memory, rules, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        rules.synthesize(project.id)

        assert synthesis.list_attention(project.id) == ()


class TestOnlyAPersonGivesARuleWeight:
    def test_attribution_is_what_makes_a_rule_active(self, factory: sessionmaker[Session]) -> None:
        memory, rules, _, project = _services(factory)
        _rule(memory, project, SECRETS_RULE)

        before = rules.synthesize(project.id)
        assert before.active == 0

        rules.record_attribution(
            project.id, before.rules[0].object_id, RuleOrigin.LAW_OR_SECURITY_AUTHORITY
        )
        after = rules.synthesize(project.id, idempotency_key="second")

        assert after.rules[0].authority is RuleAuthority.LAW
        assert after.rules[0].active is True
        assert after.active == 1
        assert after.unattributed == ()

    def test_a_rule_attributed_to_an_unaccepted_source_stays_inert(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`D-126`: deriving a control from a proposal launders the proposal."""

        memory, rules, synthesis, project = _services(factory)
        _rule(memory, project, SECRETS_RULE)
        first = rules.synthesize(project.id)
        source = synthesis.put_object(
            project.id,
            domain=KnowledgeKind.DECISION.value,
            identity_key="logging-policy",
            title="Logging policy",
            statement="We will redact credentials in logs.",
        )

        rules.record_attribution(
            project.id,
            first.rules[0].object_id,
            RuleOrigin.ARCHITECTURE_DECISION,
            source.id,
        )
        report = rules.synthesize(project.id, idempotency_key="second")

        assert report.rules[0].authority is RuleAuthority.ARCHITECTURE_CONSEQUENCE
        assert report.rules[0].active is False
        assert report.unattributed == ()

    def test_and_becomes_active_when_that_source_is_settled(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, rules, synthesis, project = _services(factory)
        _rule(memory, project, SECRETS_RULE)
        first = rules.synthesize(project.id)
        source = synthesis.put_object(
            project.id,
            domain=KnowledgeKind.DECISION.value,
            identity_key="logging-policy",
            title="Logging policy",
            statement="We will redact credentials in logs.",
        )
        rules.record_attribution(
            project.id, first.rules[0].object_id, RuleOrigin.ARCHITECTURE_DECISION, source.id
        )
        synthesis.correct_object(
            project.id,
            source.id,
            title="Logging policy",
            statement="We will redact credentials in logs.",
        )

        report = rules.synthesize(project.id, idempotency_key="third")

        assert report.rules[0].active is True

    def test_a_named_mechanism_is_what_makes_a_rule_a_control(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, rules, _, project = _services(factory)
        _rule(memory, project, SECRETS_RULE)
        first = rules.synthesize(project.id)
        rules.record_attribution(
            project.id, first.rules[0].object_id, RuleOrigin.LAW_OR_SECURITY_AUTHORITY
        )

        rules.record_mechanism(project.id, first.rules[0].object_id, CI_CHECK)
        report = rules.synthesize(project.id, idempotency_key="second")

        assert report.rules[0].mechanisms == (CI_CHECK,)
        assert report.rules[0].enforceable is True
        assert report.controls == 1

    def test_re_attributing_replaces_rather_than_stacks(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A rule has exactly one place it came from, which is `D-133`'s
        reason for one row per rule."""

        memory, rules, _, project = _services(factory)
        _rule(memory, project, SECRETS_RULE)
        report = rules.synthesize(project.id)
        object_id = report.rules[0].object_id

        first = rules.record_attribution(project.id, object_id, RuleOrigin.BUSINESS_POLICY)
        second = rules.record_attribution(
            project.id, object_id, RuleOrigin.LAW_OR_SECURITY_AUTHORITY
        )

        assert str(second.id) == str(first.id)
        stored = rules.list_attributions(project.id, object_id)
        assert len(stored) == 1
        assert stored[0].origin == RuleOrigin.LAW_OR_SECURITY_AUTHORITY.value

    def test_re_naming_the_same_mechanism_updates_rather_than_stacks(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, rules, _, project = _services(factory)
        _rule(memory, project, SECRETS_RULE)
        report = rules.synthesize(project.id)
        object_id = report.rules[0].object_id

        first = rules.record_mechanism(project.id, object_id, CI_CHECK)
        second = rules.record_mechanism(project.id, object_id, CI_CHECK.upper())

        assert str(second.id) == str(first.id)
        stored = rules.list_mechanisms(project.id, object_id)
        assert len(stored) == 1
        assert stored[0].name == CI_CHECK.upper()

    def test_nothing_can_be_attributed_to_an_object_that_is_not_a_rule(
        self, factory: sessionmaker[Session]
    ) -> None:
        _, rules, synthesis, project = _services(factory)
        other = synthesis.put_object(
            project.id,
            domain=KnowledgeKind.DECISION.value,
            identity_key="logging-policy",
            title="Logging policy",
            statement="We will redact credentials in logs.",
        )

        with pytest.raises(KnowledgeNotFoundError):
            rules.record_attribution(project.id, other.id, RuleOrigin.BUSINESS_POLICY)
        with pytest.raises(KnowledgeNotFoundError):
            rules.record_mechanism(project.id, other.id, CI_CHECK)


class TestTheRunIsIdempotent:
    def test_rerunning_writes_nothing_new(self, factory: sessionmaker[Session]) -> None:
        memory, rules, synthesis, project = _services(factory)
        _rule(memory, project, SECRETS_RULE)

        first = rules.synthesize(project.id)
        second = rules.synthesize(project.id)

        assert second.replayed is True
        assert [one.object_id for one in second.rules] == [one.object_id for one in first.rules]
        assert len(synthesis.list_objects(project.id, KnowledgeKind.RULE.value)) == 1

    def test_no_extracted_row_is_touched(self, factory: sessionmaker[Session]) -> None:
        memory, rules, synthesis, project = _services(factory)
        _rule(memory, project, SECRETS_RULE)
        before = memory.retrieve_knowledge(project.id, lifecycle=None)

        report = rules.synthesize(project.id)

        after = memory.retrieve_knowledge(project.id, lifecycle=None)
        assert len(after) == len(before)
        for rule in report.rules:
            assert synthesis.list_bindings(project.id, rule.object_id)
