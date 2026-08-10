"""Setup is configuration a person changes, not configuration they declare once.

`SetupService` could create a target, a connection and a configured value, and
could change **none** of them. That reads as an oversight and is not: every
write method had no production caller, so nothing had ever needed a second act.
The four tables are empty on the deployed system — not under-used, never written
to once — which is why the missing halves were never missed.

They are missed now. A setup surface is the first caller, and a person setting
an output repository will set the wrong one, check a credential before it is
granted, and want to see what they have already connected.

Each test here names the act that was impossible.
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
from kae_memory.domain.project_configuration import ConfigurationError
from kae_memory.domain.publication_targets import (
    AuthorizationState,
    Provider,
    TargetError,
    TargetPurpose,
)
from kae_memory.domain.setup import InferencePolicy
from kae_memory.domain.setup_questions import SetupPurpose


@pytest.fixture
def setup(factory: sessionmaker[Session]) -> SetupService:
    return SetupService(factory)


@pytest.fixture
def project_id(factory: sessionmaker[Session]) -> ProjectId:
    return MemoryService(factory).create_project("Setup changes", key="setup-change").id


def _connection(setup: SetupService, project_id: ProjectId) -> str:
    return str(
        setup.record_connection(
            project_id,
            Provider.GITHUB,
            credential_reference="env:KAE_GITHUB_TOKEN",
        ).id
    )


class TestTheOutputRepositoryCanBeChanged:
    """The act that was impossible, and the one a person does most.

    `register_target(make_default=True)` raises `DefaultConflictError` once a
    default exists, so a project's destination could be chosen **once**. That is
    not a destination; it is a commitment.
    """

    def test_a_second_target_can_become_the_default(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        connection = _connection(setup, project_id)
        first = setup.register_target(
            project_id, Provider.GITHUB, "old repo", connection_id=connection, make_default=True
        )
        second = setup.register_target(
            project_id, Provider.GITHUB, "new repo", connection_id=connection
        )

        promoted = setup.set_default(project_id, str(second.id))

        assert promoted.is_default is True
        by_id = {t.id: t for t in setup.targets(project_id)}
        assert by_id[second.id].is_default is True
        # And the old one steps down. Two defaults would make "the default"
        # ambiguous at the moment bytes are written, which is what the partial
        # unique index exists to prevent.
        assert by_id[first.id].is_default is False

    def test_the_default_a_publication_resolves_to_actually_moves(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The assertion that matters. `resolve_target` is what routes bytes.

        A `set_default` that updated a row nothing reads would be a control
        that looks like it works — this estate's own recurring defect.
        """

        connection = _connection(setup, project_id)
        setup.register_target(
            project_id, Provider.GITHUB, "old repo", connection_id=connection, make_default=True
        )
        second = setup.register_target(
            project_id, Provider.GITHUB, "new repo", connection_id=connection
        )

        setup.set_default(project_id, str(second.id))

        assert setup.resolve_target(project_id).id == second.id

    def test_the_first_default_needs_no_second_step(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """Clearing nothing must not be an error. A project with no default is
        the ordinary starting state, not a special case."""

        connection = _connection(setup, project_id)
        only = setup.register_target(
            project_id, Provider.GITHUB, "the repo", connection_id=connection
        )

        assert setup.set_default(project_id, str(only.id)).is_default is True
        assert setup.resolve_target(project_id).id == only.id

    def test_a_target_for_another_purpose_is_refused(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """A default routes one *kind* of output.

        Making a snapshot target the deliverable default would send a package
        where a snapshot was expected — a wrong destination, arrived at through
        a control that appeared to work.
        """

        connection = _connection(setup, project_id)
        snapshot = setup.register_target(
            project_id,
            Provider.GITHUB,
            "snapshots",
            purpose=TargetPurpose.SNAPSHOT,
            connection_id=connection,
        )

        with pytest.raises(TargetError) as raised:
            setup.set_default(project_id, str(snapshot.id), purpose=TargetPurpose.DELIVERABLE)

        assert "snapshot" in str(raised.value)

    def test_another_projects_target_is_not_reachable(
        self, setup: SetupService, project_id: ProjectId, factory: sessionmaker[Session]
    ) -> None:
        other = MemoryService(factory).create_project("Elsewhere", key="setup-change-2").id
        connection = _connection(setup, other)
        theirs = setup.register_target(other, Provider.GITHUB, "theirs", connection_id=connection)

        with pytest.raises(SetupNotFoundError):
            setup.set_default(project_id, str(theirs.id))

    def test_registering_two_defaults_directly_is_still_refused(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """`set_default` is the way to change it. `register_target` keeps
        refusing, so the ambiguity cannot be created by accident."""

        connection = _connection(setup, project_id)
        setup.register_target(
            project_id, Provider.GITHUB, "one", connection_id=connection, make_default=True
        )

        with pytest.raises(DefaultConflictError):
            setup.register_target(
                project_id, Provider.GITHUB, "two", connection_id=connection, make_default=True
            )


class TestAConnectionCanBeAuthorised:
    """`record_connection` only inserts.

    So a connection created `never_granted` could never become `granted`, and a
    *Connect GitHub* flow that re-recorded instead would leave a second row
    behind on every attempt — nothing makes `(project_id, provider)` unique.
    """

    def test_a_recorded_connection_can_become_granted(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        connection = _connection(setup, project_id)

        updated = setup.authorize_connection(
            project_id,
            connection,
            AuthorizationState.GRANTED,
            authorized_by="cris",
            detail="read access to crismag/KAE-Studio",
        )

        assert updated.state is AuthorizationState.GRANTED
        assert setup.authorization_for(project_id, connection) is AuthorizationState.GRANTED

    def test_granting_without_naming_who_is_refused(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The domain rule, still enforced through the new path.

        `granted` without an authorising person is an authorisation nobody
        gave, and the check belongs before the write rather than after it.
        """

        connection = _connection(setup, project_id)

        with pytest.raises(TargetError):
            setup.authorize_connection(project_id, connection, AuthorizationState.GRANTED)

        # And nothing moved. A refused transition that had already written the
        # row would be worse than no transition at all.
        assert setup.authorization_for(project_id, connection) is AuthorizationState.NEVER_GRANTED

    def test_a_check_records_when_it_happened(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """`last_verified_at` existed on the row, the dataclass, and nowhere
        else — `record_connection` always left it null."""

        from datetime import UTC, datetime

        connection = _connection(setup, project_id)
        moment = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

        setup.authorize_connection(
            project_id,
            connection,
            AuthorizationState.GRANTED,
            authorized_by="cris",
            verified_at=moment,
        )

        found = next(c for c in setup.connections(project_id) if str(c.id) == connection)
        assert found.last_verified_at is not None

    def test_a_credential_never_survives_the_round_trip(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The rule the whole record exists to hold, asserted on the new path.

        Authorising must not become the place a secret arrives.
        """

        connection = _connection(setup, project_id)

        updated = setup.authorize_connection(
            project_id, connection, AuthorizationState.GRANTED, authorized_by="cris"
        )

        assert updated.credential_reference == "env:KAE_GITHUB_TOKEN"
        assert "ghp_" not in repr(updated)

    def test_another_projects_connection_is_not_reachable(
        self, setup: SetupService, project_id: ProjectId, factory: sessionmaker[Session]
    ) -> None:
        other = MemoryService(factory).create_project("Elsewhere", key="setup-change-3").id
        theirs = _connection(setup, other)

        with pytest.raises(SetupNotFoundError):
            setup.authorize_connection(
                project_id, theirs, AuthorizationState.GRANTED, authorized_by="cris"
            )


class TestConnectionsCanBeListed:
    """There was no way to see them.

    `authorization_for` answers about one connection whose id you already hold,
    which is enough for publication and useless for a person deciding whether to
    add another. A setup surface could create connections and never show them.
    """

    def test_a_project_lists_what_it_has_connected(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        _connection(setup, project_id)
        setup.record_connection(project_id, Provider.S3, credential_reference="env:AWS_ROLE")

        providers = {c.provider for c in setup.connections(project_id)}

        assert providers == {Provider.GITHUB, Provider.S3}

    def test_a_project_with_none_lists_none(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        assert setup.connections(project_id) == ()

    def test_one_project_never_sees_another(
        self, setup: SetupService, project_id: ProjectId, factory: sessionmaker[Session]
    ) -> None:
        other = MemoryService(factory).create_project("Elsewhere", key="setup-change-4").id
        _connection(setup, other)

        assert setup.connections(project_id) == ()

    def test_no_credential_reaches_the_listing(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        setup.record_connection(
            project_id, Provider.GITHUB, credential_reference="env:KAE_GITHUB_TOKEN"
        )

        listed = setup.connections(project_id)

        # The reference travels; it is a variable name, and a person needs it to
        # know which credential they configured.
        assert listed[0].credential_reference == "env:KAE_GITHUB_TOKEN"


class TestAnsweringCannotCorruptTheConfiguration:
    """`ask` does not check `field_name`; `answer`'s configuring branch did not
    either, and it writes a `project_configuration` row.

    So one question asked about a misspelled field wrote a row that
    `ProjectConfiguration` refuses to construct — **permanently failing
    `GET /setup` for that project**, with no way to remove it through this
    service.
    """

    def test_a_settled_answer_about_an_unknown_field_configures_nothing(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        question = setup.ask(
            project_id,
            SetupPurpose.GENERATION,
            "Which repository?",
            field_name="primry_repository",  # the typo that used to poison the project
            policy=InferencePolicy.ASK,
        )

        setup.answer(project_id, str(question.id), "crismag/KAE-Studio", actor="cris")

        # The project is still readable, which is the whole point.
        assert setup.configuration(project_id).as_dict() == {}
        assert setup.readiness(project_id) is not None

    def test_the_answer_itself_is_still_recorded(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """Skipping the write must not discard the answer.

        A settled question is not made unsettled by having nowhere to put its
        value — the disposition is the durable part.
        """

        question = setup.ask(
            project_id,
            SetupPurpose.GENERATION,
            "Which repository?",
            field_name="primry_repository",
            policy=InferencePolicy.ASK,
        )

        answered = setup.answer(project_id, str(question.id), "crismag/KAE-Studio", actor="cris")

        assert answered.answer == "crismag/KAE-Studio"
        assert answered.disposition is Disposition.ANSWERED

    def test_a_known_field_still_configures(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The guard must not cost the working path."""

        question = setup.ask(
            project_id,
            SetupPurpose.GENERATION,
            "Which repository?",
            field_name="primary_repository",
            policy=InferencePolicy.ASK,
        )

        setup.answer(project_id, str(question.id), "crismag/KAE-Studio", actor="cris")

        assert setup.configuration(project_id).effective("primary_repository") == (
            "crismag/KAE-Studio"
        )

    def test_set_value_still_refuses_the_same_field(
        self, setup: SetupService, project_id: ProjectId
    ) -> None:
        """The two paths agree. `set_value` raises rather than skipping,
        because there the caller named the field directly and a silent no-op
        would lose their intent."""

        from kae_memory.domain.setup import ValueState

        with pytest.raises(ConfigurationError):
            setup.set_value(
                project_id,
                "primry_repository",
                "crismag/KAE-Studio",
                ValueState.CONFIRMED,
                confirmed_by="cris",
            )
