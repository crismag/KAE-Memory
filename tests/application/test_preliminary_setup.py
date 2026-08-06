"""Preliminary setup: configuration, not knowledge (N24-N28).

Four records and one workflow. The assertions here are about the boundaries
between them, because that is where this design earns its complexity:

    setup readiness is reported apart from knowledge readiness;
    only setup blocks, and never because knowledge is thin;
    a setup question is not a clarification, in either direction;
    a knowledge statement never routes a publication;
    a credential never reaches configuration, a target, or a response.

The last one is asserted several ways deliberately. A secret that reaches a
record has already been written somewhere readable, and removing it afterwards
does not unwrite it.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.application.setup_service import (
    DefaultConflictError,
    SetupNotFoundError,
    SetupService,
)
from kae_memory.domain.dispositions import Disposition
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.project_configuration import ConfigurationError, ConfiguredValue
from kae_memory.domain.publication_targets import (
    AuthorizationState,
    Provider,
    ProviderConnection,
    PublicationTarget,
    TargetError,
    TargetPurpose,
    ensure_no_inline_destination,
)
from kae_memory.domain.setup import (
    InferencePolicy,
    InferredValue,
    SetupError,
    SetupState,
    ValueState,
)
from kae_memory.domain.setup_questions import SetupPurpose


@pytest.fixture
def setup(factory: sessionmaker[Session]) -> SetupService:
    return SetupService(factory)


@pytest.fixture
def project_id(factory: sessionmaker[Session]) -> ProjectId:
    return MemoryService(factory).create_project("Sparse Inbox", key="setup-inbox").id


class TestAProjectStartsWithAlmostNothing:
    def test_configuration_is_empty_and_that_is_normal(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """An idea described in a sentence has no repository, no branch, and no
        publication target, and nothing about it is wrong."""

        configuration = setup.configuration(project_id)

        assert configuration.unknown_fields()
        assert configuration.effective("primary_repository") is None

    def test_setup_starts_not_started(self, setup: SetupService, project_id: ProjectId) -> None:
        assert setup.readiness(project_id).state is SetupState.NOT_STARTED

    def test_an_absent_target_does_not_make_a_new_project_look_stuck(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """Nobody has asked to publish. Reporting `needs_input` for a decision
        the project has not reached would make every new project look stuck —
        and a person who sees that on every project stops reading it."""

        readiness = setup.readiness(project_id)

        assert readiness.state is not SetupState.NEEDS_INPUT
        assert readiness.blocks("publication") is True

    def test_configuring_something_reaches_ready_for_generation(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        setup.set_value(
            project_id, "project_kind", "prototype", ValueState.CONFIRMED, confirmed_by="cris"
        )

        assert setup.readiness(project_id).state is SetupState.READY_FOR_GENERATION

    def test_asking_something_reaches_sufficient_to_begin(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The common early state, and not a deficiency: everything KAE does
        for a sparse project works from here."""

        setup.ask(project_id, SetupPurpose.ACQUISITION, "Which repository?", "primary_repository")

        assert setup.readiness(project_id).state is SetupState.SUFFICIENT_TO_BEGIN

    def test_an_unknown_field_is_refused_rather_than_created(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """A misspelled field would configure nothing and look configured."""

        with pytest.raises(ConfigurationError, match="unknown configuration field"):
            setup.set_value(
                project_id, "primry_repository", "x", ValueState.CONFIRMED, confirmed_by="cris"
            )


class TestSetupReadinessIsNotKnowledgeReadiness:
    def test_a_sparse_project_with_a_local_target_blocks_nothing(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The line this whole phase exists to hold. Knowledge sparsity must
        never appear as a setup block — that is the readiness gate the product
        context rejected, wearing a new name."""

        setup.register_target(project_id, Provider.LOCAL, "local files", make_default=True)

        readiness = setup.readiness(project_id)

        assert readiness.blocks_anything is False
        assert readiness.state is SetupState.READY_FOR_PUBLICATION

    def test_no_gap_mentions_knowledge(self, setup: SetupService, project_id: ProjectId) -> None:
        """Every blocking gap must name an unmade choice or a missing
        authorisation, never how much is known."""

        readiness = setup.readiness(project_id)

        assert all(
            "know" not in gap.reason.lower() and "readiness" not in gap.reason.lower()
            for gap in readiness.gaps
        )

    def test_an_unregistered_target_blocks_publication_only(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """Per capability, because that is how a person acts on it."""

        readiness = setup.readiness(project_id)

        assert readiness.blocks("publication") is True
        assert readiness.blocks("generation") is False

    def test_a_gap_says_what_to_do(self, setup: SetupService, project_id: ProjectId) -> None:
        """A gap with no next action is a complaint."""

        gaps = setup.readiness(project_id).gaps

        assert gaps
        assert all(gap.next_action.strip() for gap in gaps)


class TestTheTwoQueuesNeverMix:
    def test_a_setup_question_is_not_a_clarification(
        self, setup: SetupService, factory: sessionmaker[Session], project_id: ProjectId
    ) -> None:
        """ "What should this product do?" and "where should this publish?" are
        different conversations, and interleaving them makes both worse."""

        from kae_memory.application.clarification_service import ClarificationService
        from kae_memory.application.readiness_service import ReadinessService

        ReadinessService(factory).install_template()
        setup.ask(
            project_id,
            SetupPurpose.PUBLICATION,
            "Where should deliverables go?",
            "default_publication_target",
        )

        clarifications = ClarificationService(factory).open_questions(project_id)

        assert all("deliverables go" not in question.question for question in clarifications)

    def test_answering_one_configures_and_does_not_touch_knowledge(
        self, setup: SetupService, factory: sessionmaker[Session], project_id: ProjectId
    ) -> None:
        """Recording it as knowledge would put a configuration decision in
        front of a reviewer as something to confirm about the product."""

        asked = setup.ask(
            project_id,
            SetupPurpose.PUBLICATION,
            "Where should deliverables go?",
            "default_publication_target",
        )

        setup.answer(project_id, str(asked.id), "local files", actor="cris")

        assert setup.configuration(project_id).effective("default_publication_target") == (
            "local files"
        )
        assert MemoryService(factory).retrieve_knowledge(project_id, lifecycle=None) == ()

    def test_asking_twice_about_one_field_asks_once(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        first = setup.ask(
            project_id, SetupPurpose.PUBLICATION, "Where?", "default_publication_target"
        )
        second = setup.ask(
            project_id, SetupPurpose.PUBLICATION, "Where?", "default_publication_target"
        )

        assert first.id == second.id
        assert len(setup.open_questions(project_id)) == 1


class TestNotKnowingConfiguresNothing:
    def test_a_non_settling_answer_leaves_it_open(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The same distinction as a clarification (N36). "Pick something
        reasonable for now" is a real answer and not a default anyone set."""

        asked = setup.ask(
            project_id, SetupPurpose.PUBLICATION, "Where?", "default_publication_target"
        )

        setup.answer(
            project_id,
            str(asked.id),
            "I don't know yet",
            actor="cris",
            disposition=Disposition.UNKNOWN_BY_USER,
        )

        assert setup.configuration(project_id).effective("default_publication_target") is None
        assert len(setup.open_questions(project_id)) == 1

    def test_a_settling_answer_closes_it(self, setup: SetupService, project_id: ProjectId) -> None:
        asked = setup.ask(
            project_id, SetupPurpose.PUBLICATION, "Where?", "default_publication_target"
        )

        setup.answer(project_id, str(asked.id), "local files", actor="cris")

        assert setup.open_questions(project_id) == ()


class TestKnowledgeNeverRoutesAPublication:
    def test_a_derived_value_records_where_it_came_from(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """Derivation is legitimate — **once, deliberately, recorded**. What is
        not is publication searching prose at the moment bytes are written."""

        setup.set_value(
            project_id,
            "primary_repository",
            "crismag/KAE-Studio",
            ValueState.INFERRED,
            evidence="derived from a confirmed statement",
            derived_from_knowledge_id="k-1",
        )

        value = setup.configuration(project_id).get("primary_repository")

        assert value.derived_from_knowledge_id == "k-1"
        assert value.in_use is True

    def test_a_suggestion_does_not_take_effect(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The entire reason `suggested` is its own state: what KAE would
        choose is not what it chose."""

        setup.set_value(
            project_id,
            "primary_repository",
            "crismag/KAE-Studio",
            ValueState.SUGGESTED,
            evidence="the git remote in the working directory",
        )

        assert setup.configuration(project_id).effective("primary_repository") is None

    def test_a_value_in_use_that_kae_worked_out_is_disclosed(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        setup.set_value(
            project_id,
            "primary_repository",
            "crismag/KAE-Studio",
            ValueState.INFERRED,
            evidence="the git remote",
        )

        assert setup.configuration(project_id).disclosures()

    def test_an_inference_needs_evidence(self) -> None:
        """An inference nobody can check is a guess wearing a better word."""

        with pytest.raises(SetupError, match="no evidence"):
            InferredValue("primary_repository", "crismag/KAE-Studio", "", 0.9)

    def test_a_confirmed_value_names_who_confirmed_it(self) -> None:
        """An unattributed confirmation records that the system agreed with
        itself (FR-005)."""

        with pytest.raises(ConfigurationError, match="confirmed by nobody"):
            ConfiguredValue("primary_repository", "x", ValueState.CONFIRMED)


class TestCredentialsNeverGetWrittenDown:
    def test_a_credential_field_is_refused_by_configuration(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        with pytest.raises(ConfigurationError, match="names a credential"):
            ConfiguredValue("github_token", "ghp_x", ValueState.CONFIRMED, confirmed_by="cris")

    def test_a_credential_is_never_inferred_at_any_policy(self) -> None:
        """A credential is granted, never worked out."""

        with pytest.raises(SetupError, match="cannot be inferred"):
            InferredValue("access_key", "AKIA...", "found it in the environment", 0.9)

    def test_target_configuration_may_not_carry_a_secret(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """A bucket name is configuration; the key that writes to it is not."""

        connection = setup.record_connection(project_id, Provider.S3)

        with pytest.raises(TargetError, match="may not carry credentials"):
            setup.register_target(
                project_id,
                Provider.S3,
                "artifacts",
                configuration={"bucket": "kae", "secret_key": "shhh"},
                connection_id=str(connection.id),
            )

    def test_a_connection_holds_a_reference_not_a_secret(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """This record is returned to callers. A secret in it is a secret
        disclosed, and redacting it on the way out does not unwrite it."""

        from kae_memory.domain.publication_targets import ConnectionId

        with pytest.raises(TargetError, match="looks like a credential"):
            ProviderConnection(
                id=ConnectionId("c-1"),
                project_id=project_id,
                provider=Provider.GITHUB,
                credential_reference="ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            )

    def test_a_reference_to_where_a_credential_lives_is_fine(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        connection = setup.record_connection(
            project_id, Provider.GITHUB, credential_reference="env:KAE_GITHUB_TOKEN"
        )

        assert connection.credential_reference == "env:KAE_GITHUB_TOKEN"

    def test_a_granted_connection_names_who_granted_it(self, project_id: ProjectId) -> None:
        """An unattributed grant records that the system permitted itself."""

        from kae_memory.domain.publication_targets import ConnectionId

        with pytest.raises(TargetError, match="names nobody"):
            ProviderConnection(
                id=ConnectionId("c-1"),
                project_id=project_id,
                provider=Provider.GITHUB,
                state=AuthorizationState.GRANTED,
            )


class TestARequestCannotNameItsOwnDestination:
    def test_an_inline_bucket_is_refused(self) -> None:
        """A request that could name a destination would make every
        authorisation check advisory: the check runs against a registered
        target while the bytes go somewhere else."""

        with pytest.raises(TargetError, match="may not name a destination inline"):
            ensure_no_inline_destination({"bucket": "somebody-elses-bucket"})

    def test_an_inline_repository_is_refused(self) -> None:
        with pytest.raises(TargetError, match="may not name a destination inline"):
            ensure_no_inline_destination({"repository": "crismag/anything"})

    def test_an_absolute_path_is_refused(self) -> None:
        with pytest.raises(TargetError, match="may not name a destination inline"):
            ensure_no_inline_destination({"path": "/etc"})

    def test_a_target_id_is_allowed(self) -> None:
        ensure_no_inline_destination({"target_id": "t-1", "deliverable_id": "d-1"})


class TestDefaultsAndOverrides:
    def test_a_request_with_no_target_resolves_to_the_default(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        registered = setup.register_target(
            project_id, Provider.LOCAL, "local files", make_default=True
        )

        assert setup.resolve_target(project_id).id == registered.id

    def test_a_named_target_overrides_without_becoming_the_default(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """An override that silently became the default would route the next
        publication somewhere nobody chose."""

        default = setup.register_target(
            project_id, Provider.LOCAL, "local files", make_default=True
        )
        other = setup.register_target(project_id, Provider.LOCAL, "scratch")

        assert setup.resolve_target(project_id, target_id=str(other.id)).id == other.id
        assert setup.resolve_target(project_id).id == default.id

    def test_a_second_default_for_one_purpose_is_refused(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """Two would make "the default" ambiguous at the moment bytes are
        written."""

        setup.register_target(project_id, Provider.LOCAL, "local files", make_default=True)

        with pytest.raises(DefaultConflictError):
            setup.register_target(project_id, Provider.LOCAL, "other", make_default=True)

    def test_defaults_for_different_purposes_coexist(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        setup.register_target(
            project_id,
            Provider.LOCAL,
            "deliverables",
            purpose=TargetPurpose.DELIVERABLE,
            make_default=True,
        )
        setup.register_target(
            project_id,
            Provider.LOCAL,
            "snapshots",
            purpose=TargetPurpose.SNAPSHOT,
            make_default=True,
        )

        assert setup.resolve_target(project_id, purpose=TargetPurpose.SNAPSHOT).name == "snapshots"

    def test_no_default_and_no_target_named_is_an_actionable_refusal(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        with pytest.raises(SetupNotFoundError, match="no default"):
            setup.resolve_target(project_id)


class TestAnUnauthorisedTargetIsVisibleAndUnusable:
    def test_it_stays_registered(self, setup: SetupService, project_id: ProjectId) -> None:
        """A target that vanished when its authorisation expired would take the
        decision with it, and the person would be asked to choose a destination
        they already chose."""

        connection = setup.record_connection(project_id, Provider.GITHUB)
        setup.register_target(
            project_id, Provider.GITHUB, "studio", connection_id=str(connection.id)
        )

        assert len(setup.targets(project_id)) == 1

    def test_it_reports_why_rather_than_only_that(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """ "Unavailable" leaves a person guessing between "I never set this
        up", "it stopped working", and "somebody turned it off"."""

        connection = setup.record_connection(project_id, Provider.GITHUB)
        setup.register_target(
            project_id, Provider.GITHUB, "studio", connection_id=str(connection.id)
        )

        reasons = [gap.reason for gap in setup.readiness(project_id).gaps]

        assert any("nobody has authorised" in reason for reason in reasons)

    def test_an_unverified_connection_is_not_usable(self, project_id: ProjectId) -> None:
        """Attempting anyway would mean the first thing a person learns about a
        broken connection is a failed publication."""

        from kae_memory.domain.publication_targets import TargetId

        target = PublicationTarget(
            id=TargetId("t-1"),
            project_id=project_id,
            provider=Provider.S3,
            name="artifacts",
            connection_id="c-1",
        )

        assert target.available(AuthorizationState.UNVERIFIED) is False

    def test_a_non_local_target_needs_a_connection(self, project_id: ProjectId) -> None:
        """Otherwise it is selectable and unusable with no way to say why."""

        from kae_memory.domain.publication_targets import TargetId

        with pytest.raises(TargetError, match="needs a connection"):
            PublicationTarget(
                id=TargetId("t-1"),
                project_id=project_id,
                provider=Provider.GITHUB,
                name="studio",
            )

    def test_a_local_target_needs_none(self, project_id: ProjectId) -> None:
        from kae_memory.domain.publication_targets import TargetId

        target = PublicationTarget(
            id=TargetId("t-1"),
            project_id=project_id,
            provider=Provider.LOCAL,
            name="local files",
        )

        assert target.available(AuthorizationState.NEVER_GRANTED) is True


class TestAuthorizationIsAlwaysBlocking:
    def test_an_authorization_question_cannot_be_non_blocking(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """Permission is granted, and proceeding without it is proceeding
        without it."""

        from kae_memory.domain.setup_questions import SetupQuestionError

        with pytest.raises(SetupQuestionError, match="always blocking"):
            setup.ask(
                project_id,
                SetupPurpose.AUTHORIZATION,
                "May KAE push to GitHub?",
                "github_authorization",
                blocking=False,
                policy=InferencePolicy.BLOCK,
            )

    def test_a_blocking_question_moves_setup_to_needs_input(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        setup.ask(
            project_id,
            SetupPurpose.PUBLICATION,
            "Where should deliverables go?",
            "default_publication_target",
            blocking=True,
        )

        assert setup.readiness(project_id).state is SetupState.NEEDS_INPUT

    def test_a_suggestion_without_evidence_is_refused(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """A person reading it could only judge whether to trust the machine."""

        from kae_memory.domain.setup_questions import SetupQuestionError

        with pytest.raises(SetupQuestionError, match="no evidence"):
            setup.ask(
                project_id,
                SetupPurpose.PUBLICATION,
                "Where?",
                "default_publication_target",
                suggested_answer="local files",
            )
