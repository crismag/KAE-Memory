"""Rendering, verification, and publication (N21, N29, N30).

The properties under test are the ones that make a published file trustworthy:

    the same deliverable renders byte-identically;
    a deliverable that cannot be proven refuses rather than rendering something;
    nothing is written outside the configured root, under any input;
    a failed attempt never touches the deliverable;
    no signed URL is ever stored.

Every write goes to a pytest `tmp_path`. Nothing here writes into the
repository, a user directory, or anywhere a test could leave a file behind.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assembly_service import AssemblyPurpose, AssemblyService
from kae_memory.application.deliverable_service import DeliverableService
from kae_memory.application.providers.local import (
    LocalFilesystemProvider,
    LocalPublicationError,
    OutsideRootError,
)
from kae_memory.application.publication_service import PublicationRefused, PublicationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.render_service import RenderService, package_hash
from kae_memory.application.setup_service import SetupService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.publication import (
    AttemptState,
    ErrorCategory,
    PublicationAttempt,
    PublicationError,
    ensure_attempt_transition,
)
from kae_memory.domain.publication_targets import AuthorizationState, Provider

STATEMENT = "Captured thoughts are stored as markdown files."


@pytest.fixture
def project_id(factory: sessionmaker[Session]) -> ProjectId:
    readiness = ReadinessService(factory)
    readiness.install_template()
    memory = MemoryService(factory)
    project = memory.create_project("Sparse Inbox", key="publish-inbox")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "publish-seed")
    written = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, STATEMENT, "seed")]
    )
    readiness.assign_area(project.id, written[0].id, "constraints_and_assumptions")
    memory.confirm_knowledge(written[0].id)
    return project.id


@pytest.fixture
def deliverable_id(factory: sessionmaker[Session], project_id: ProjectId) -> str:
    assembly = AssemblyService(factory).assemble(project_id, AssemblyPurpose.DISCOVERY)
    recorded, _ = DeliverableService(factory).record(project_id, assembly, recorded_by="cris")
    return str(recorded.id)


@pytest.fixture
def render(factory: sessionmaker[Session]) -> RenderService:
    return RenderService(factory)


@pytest.fixture
def setup(factory: sessionmaker[Session]) -> SetupService:
    return SetupService(factory)


class TestRenderingIsDeterministic:
    def test_two_renders_are_byte_identical(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str
    ) -> None:
        """Nothing here reads a clock or a random source. A timestamp in the
        output would be true and would make the hash useless for the one thing
        it is for."""

        first = render.render(project_id, deliverable_id)
        second = render.render(project_id, deliverable_id)

        assert [a.content for a in first.artifacts] == [a.content for a in second.artifacts]
        assert package_hash(first.artifacts) == package_hash(second.artifacts)

    def test_it_produces_content(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str
    ) -> None:
        package = render.render(project_id, deliverable_id)

        assert package.artifacts
        assert package.total_size > 0

    def test_it_verifies_against_what_was_recorded(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str
    ) -> None:
        package = render.render(project_id, deliverable_id)

        assert package.verified is True
        assert package.mismatches == ()

    def test_verified_is_always_present(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str
    ) -> None:
        """A field a caller infers from the absence of an error is a field that
        gets forgotten."""

        assert render.render(project_id, deliverable_id).verified is not None

    def test_it_names_the_renderer(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str
    ) -> None:
        """A renderer change alters bytes, and a caller comparing a new render
        against an old hash needs to know which produced it."""

        assert render.render(project_id, deliverable_id).renderer_version

    def test_it_writes_nothing(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str, tmp_path: Path
    ) -> None:
        """Provider-neutral means no destination at all, not a default one."""

        render.render(project_id, deliverable_id)

        assert list(tmp_path.iterdir()) == []


class TestReproducibilityIsAnAnswerableQuestion:
    def test_an_unchanged_project_is_still_reproducible(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str
    ) -> None:
        assert render.is_still_reproducible(project_id, deliverable_id) is True

    def test_a_moved_project_is_not(
        self,
        render: RenderService,
        factory: sessionmaker[Session],
        project_id: ProjectId,
        deliverable_id: str,
    ) -> None:
        """Routinely false for a project that moved on, and that is not a fault
        in the deliverable — which is why it is a separate question from
        whether it renders."""

        memory = MemoryService(factory)
        run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "publish-more")
        written = memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, "A second thing.", "seed")],
        )
        ReadinessService(factory).assign_area(
            project_id, written[0].id, "constraints_and_assumptions"
        )
        memory.confirm_knowledge(written[0].id)

        assert render.is_still_reproducible(project_id, deliverable_id) is False

    def test_a_moved_project_still_renders_the_old_deliverable(
        self,
        render: RenderService,
        factory: sessionmaker[Session],
        project_id: ProjectId,
        deliverable_id: str,
    ) -> None:
        """The point of pinning. The old deliverable keeps saying what it said,
        which is the only reason it is worth keeping."""

        memory = MemoryService(factory)
        run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "publish-more")
        memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, "A second thing.", "seed")],
        )

        assert render.render(project_id, deliverable_id).verified is True


class TestNothingEscapesTheRoot:
    def test_a_traversal_is_refused(self, tmp_path: Path) -> None:
        provider = LocalFilesystemProvider(tmp_path)

        with pytest.raises(OutsideRootError, match="traverses upward"):
            provider._resolve("../escape")

    def test_an_absolute_path_is_refused(self, tmp_path: Path) -> None:
        provider = LocalFilesystemProvider(tmp_path)

        with pytest.raises(OutsideRootError, match="absolute path"):
            provider._resolve("/etc/passwd")

    def test_a_null_byte_is_refused(self, tmp_path: Path) -> None:
        provider = LocalFilesystemProvider(tmp_path)

        with pytest.raises(LocalPublicationError, match="null byte"):
            provider._resolve("fine\x00/../../etc")

    def test_a_symlink_escape_is_refused(self, tmp_path: Path) -> None:
        """The defence that survives an input nobody anticipated: it stops
        asking what the string looks like and asks where the file would go."""

        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside)
        provider = LocalFilesystemProvider(root)

        with pytest.raises(OutsideRootError, match="outside the configured root"):
            provider._resolve("link/../../outside/file.md")

    def test_an_empty_location_is_refused(self, tmp_path: Path) -> None:
        provider = LocalFilesystemProvider(tmp_path)

        with pytest.raises(LocalPublicationError, match="cannot be empty"):
            provider._resolve("   ")

    def test_a_disabled_provider_writes_nothing(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str, tmp_path: Path
    ) -> None:
        """A configuration decision, not a failure. Hosted deployments turn it
        off, and a server writing files nobody can reach fills a disk."""

        provider = LocalFilesystemProvider(tmp_path, enabled=False)
        package = render.render(project_id, deliverable_id)

        with pytest.raises(LocalPublicationError, match="disabled"):
            provider.publish(package, "deliverables/x")
        assert list(tmp_path.iterdir()) == []


class TestWritingIsSafeAndDeliberate:
    def test_it_writes_the_artifacts(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str, tmp_path: Path
    ) -> None:
        provider = LocalFilesystemProvider(tmp_path)
        package = render.render(project_id, deliverable_id)

        written = provider.publish(package, "deliverables/one")

        assert written.files_written == len(package.artifacts)
        assert list(tmp_path.rglob("*.md"))

    def test_a_collision_is_refused_unless_meant(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str, tmp_path: Path
    ) -> None:
        """Publishing over content nobody asked to replace destroys it."""

        provider = LocalFilesystemProvider(tmp_path)
        package = render.render(project_id, deliverable_id)
        provider.publish(package, "deliverables/one")

        with pytest.raises(LocalPublicationError, match="already exists"):
            provider.publish(package, "deliverables/one")

    def test_overwrite_means_it(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str, tmp_path: Path
    ) -> None:
        provider = LocalFilesystemProvider(tmp_path)
        package = render.render(project_id, deliverable_id)
        provider.publish(package, "deliverables/one")

        assert provider.publish(package, "deliverables/one", overwrite=True).files_written

    def test_no_staged_files_survive(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str, tmp_path: Path
    ) -> None:
        """Staged then renamed: a crash halfway leaves the previous content,
        not half the new content."""

        provider = LocalFilesystemProvider(tmp_path)
        provider.publish(render.render(project_id, deliverable_id), "deliverables/one")

        assert not list(tmp_path.rglob("*.staged"))

    def test_the_reference_is_relative_to_the_root(
        self, render: RenderService, project_id: ProjectId, deliverable_id: str, tmp_path: Path
    ) -> None:
        """An absolute path in a durable record is a fact about one machine,
        and it will be read on another."""

        provider = LocalFilesystemProvider(tmp_path)

        written = provider.publish(render.render(project_id, deliverable_id), "deliverables/one")

        assert not written.reference.startswith("/")
        assert written.reference == "deliverables/one"


class TestThePublicationPathRecordsEverything:
    def test_a_successful_publication_is_recorded(
        self,
        factory: sessionmaker[Session],
        setup: SetupService,
        project_id: ProjectId,
        deliverable_id: str,
        tmp_path: Path,
    ) -> None:
        setup.register_target(project_id, Provider.LOCAL, "local files", make_default=True)
        service = PublicationService(factory, local=LocalFilesystemProvider(tmp_path))

        attempt = service.publish(project_id, deliverable_id, actor="cris")

        assert attempt.succeeded is True
        assert attempt.external_reference
        assert attempt.package_hash

    def test_a_missing_target_is_recorded_as_configuration(
        self,
        factory: sessionmaker[Session],
        project_id: ProjectId,
        deliverable_id: str,
        tmp_path: Path,
    ) -> None:
        service = PublicationService(factory, local=LocalFilesystemProvider(tmp_path))

        attempt = service.publish(project_id, deliverable_id, actor="cris")

        assert attempt.state is AttemptState.FAILED
        assert attempt.error_category is ErrorCategory.CONFIGURATION
        assert service.history(project_id) == (attempt,)

    def test_an_unauthorised_target_is_refused_and_recorded(
        self,
        factory: sessionmaker[Session],
        setup: SetupService,
        project_id: ProjectId,
        deliverable_id: str,
        tmp_path: Path,
    ) -> None:
        connection = setup.record_connection(project_id, Provider.GITHUB)
        setup.register_target(
            project_id,
            Provider.GITHUB,
            "studio",
            connection_id=str(connection.id),
            make_default=True,
        )
        service = PublicationService(factory, local=LocalFilesystemProvider(tmp_path))

        with pytest.raises(PublicationRefused) as raised:
            service.publish(project_id, deliverable_id, actor="cris")

        assert raised.value.attempt.error_category is ErrorCategory.AUTHORIZATION
        assert len(service.history(project_id)) == 1

    def test_a_failure_leaves_the_deliverable_untouched(
        self,
        factory: sessionmaker[Session],
        project_id: ProjectId,
        deliverable_id: str,
        tmp_path: Path,
    ) -> None:
        """Something between a document and a bucket did not work. The document
        is exactly as good as it was."""

        deliverables = DeliverableService(factory)
        before = deliverables.get(project_id, deliverable_id)
        service = PublicationService(factory, local=LocalFilesystemProvider(tmp_path))

        service.publish(project_id, deliverable_id, actor="cris")

        after = deliverables.get(project_id, deliverable_id)
        assert after.state == before.state
        assert after.content_hash == before.content_hash
        assert after.publication_eligible is True

    def test_history_keeps_every_attempt(
        self,
        factory: sessionmaker[Session],
        setup: SetupService,
        project_id: ProjectId,
        deliverable_id: str,
        tmp_path: Path,
    ) -> None:
        """ "It failed twice and then worked" is exactly the history an operator
        needs when it fails a third time."""

        service = PublicationService(factory, local=LocalFilesystemProvider(tmp_path))
        service.publish(project_id, deliverable_id, actor="cris")
        setup.register_target(project_id, Provider.LOCAL, "local files", make_default=True)
        service.publish(project_id, deliverable_id, actor="cris")

        history = service.history(project_id, deliverable_id)

        assert len(history) == 2
        assert [attempt.succeeded for attempt in history] == [False, True]

    def test_an_unimplemented_provider_records_rather_than_pretending(
        self,
        factory: sessionmaker[Session],
        setup: SetupService,
        project_id: ProjectId,
        deliverable_id: str,
        tmp_path: Path,
    ) -> None:
        """S3 and GitHub are not implemented in this version. Saying so, with
        the attempt recorded, is better than a plausible silence."""

        connection = setup.record_connection(
            project_id, Provider.S3, state=AuthorizationState.GRANTED, authorized_by="cris"
        )
        setup.register_target(
            project_id,
            Provider.S3,
            "artifacts",
            configuration={"bucket": "kae"},
            connection_id=str(connection.id),
            make_default=True,
        )
        service = PublicationService(factory, local=LocalFilesystemProvider(tmp_path))

        with pytest.raises(PublicationRefused, match="not implemented"):
            service.publish(project_id, deliverable_id, actor="cris")

        assert service.history(project_id)[-1].error_category is ErrorCategory.PROVIDER


class TestTheAttemptModelRefusesTheWrongShapes:
    def test_a_signed_url_is_never_stored(self, project_id: ProjectId) -> None:
        """A presigned URL is a credential with a timer. Stored, it is useless
        when read and dangerous until then."""

        from kae_memory.domain.publication import AttemptId

        with pytest.raises(PublicationError, match="signed URL"):
            PublicationAttempt(
                id=AttemptId("a-1"),
                project_id=project_id,
                deliverable_id="d-1",
                target_id="t-1",
                provider="s3",
                external_reference="https://s3.example/x?X-Amz-Signature=abc",
            )

    def test_a_plain_reference_is_fine(self, project_id: ProjectId) -> None:
        from kae_memory.domain.publication import AttemptId

        attempt = PublicationAttempt(
            id=AttemptId("a-1"),
            project_id=project_id,
            deliverable_id="d-1",
            target_id="t-1",
            provider="local",
            external_reference="deliverables/one",
        )

        assert attempt.external_reference == "deliverables/one"

    def test_publishing_without_verification_is_refused(self, project_id: ProjectId) -> None:
        """Writing unverified bytes puts content under an identity that may no
        longer describe it."""

        from kae_memory.domain.publication import AttemptId

        with pytest.raises(PublicationError, match="without verification"):
            PublicationAttempt(
                id=AttemptId("a-1"),
                project_id=project_id,
                deliverable_id="d-1",
                target_id="t-1",
                provider="local",
                state=AttemptState.PUBLISHED,
                external_reference="deliverables/one",
            )

    def test_a_finished_attempt_does_not_reopen(self) -> None:
        """A retry is a new attempt. Reopening would erase the fact that this
        one ended."""

        with pytest.raises(PublicationError, match="is finished"):
            ensure_attempt_transition(AttemptState.FAILED, AttemptState.RENDERING)

    def test_an_integrity_failure_is_not_retryable(self, project_id: ProjectId) -> None:
        """The same deliverable produces the same mismatch, and a retry loop
        turns one problem into a sustained one."""

        from kae_memory.domain.publication import AttemptId

        attempt = PublicationAttempt(
            id=AttemptId("a-1"),
            project_id=project_id,
            deliverable_id="d-1",
            target_id="t-1",
            provider="local",
            state=AttemptState.VERIFICATION_FAILED,
            error_category=ErrorCategory.INTEGRITY,
            error_detail="hash mismatch",
        )

        assert attempt.retryable is False

    def test_a_transient_failure_is_retryable(self, project_id: ProjectId) -> None:
        from kae_memory.domain.publication import AttemptId

        attempt = PublicationAttempt(
            id=AttemptId("a-1"),
            project_id=project_id,
            deliverable_id="d-1",
            target_id="t-1",
            provider="local",
            state=AttemptState.FAILED,
            error_category=ErrorCategory.TRANSIENT,
            error_detail="the provider timed out",
        )

        assert attempt.retryable is True

    def test_a_categorised_failure_needs_a_detail(self, project_id: ProjectId) -> None:
        """A category with no detail leaves whoever reads it with no way to
        act on it."""

        from kae_memory.domain.publication import AttemptId

        with pytest.raises(PublicationError, match="no detail"):
            PublicationAttempt(
                id=AttemptId("a-1"),
                project_id=project_id,
                deliverable_id="d-1",
                target_id="t-1",
                provider="local",
                error_category=ErrorCategory.TRANSIENT,
            )
