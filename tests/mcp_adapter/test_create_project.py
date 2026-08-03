"""Creating a project over MCP.

The one write that brings a subject into being rather than adding evidence
about one. Two things make it usable: a name is enough, and creating twice is
not an error.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.memory_service import MemoryService, project_key_from_name
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.mcp import tools
from kae_memory.mcp.errors import InvalidArgumentError
from kae_memory.mcp.server import dispatch


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
    )


class TestOneLineIsEnough:
    def test_a_name_is_the_only_requirement(self, context: tools.ToolContext) -> None:
        payload = dispatch(context, "kae_create_project", {"name": "KAE-Memory"})

        assert payload["created"] is True
        assert payload["name"] == "KAE-Memory"
        assert payload["project_id"]

    def test_the_key_is_derived_from_the_name(self, context: tools.ToolContext) -> None:
        """A generated suffix is not something anyone can read back later."""

        payload = dispatch(context, "kae_create_project", {"name": "KAE-Memory"})

        assert payload["key"] == "kae-memory"

    def test_an_explicit_key_is_honoured(self, context: tools.ToolContext) -> None:
        payload = dispatch(context, "kae_create_project", {"name": "KAE-Memory", "key": "kae-mem"})

        assert payload["key"] == "kae-mem"

    def test_a_description_is_optional_and_kept(self, context: tools.ToolContext) -> None:
        payload = dispatch(
            context, "kae_create_project", {"name": "Reporting", "description": "Monthly."}
        )

        assert payload["description"] == "Monthly."


class TestIdempotence:
    def test_creating_twice_returns_the_same_project(self, context: tools.ToolContext) -> None:
        """An agent that loses its response must be able to retry."""

        first = dispatch(context, "kae_create_project", {"name": "KAE-Memory"})
        second = dispatch(context, "kae_create_project", {"name": "KAE-Memory"})

        assert second["project_id"] == first["project_id"]
        assert first["created"] is True
        assert second["created"] is False

    def test_a_repeat_says_it_changed_nothing(self, context: tools.ToolContext) -> None:
        dispatch(context, "kae_create_project", {"name": "KAE-Memory"})

        second = dispatch(context, "kae_create_project", {"name": "KAE-Memory"})

        assert any("already existed" in step for step in second["next_steps"])

    def test_a_repeat_does_not_overwrite_the_description(self, context: tools.ToolContext) -> None:
        """Resolving to an existing project must not edit it."""

        dispatch(context, "kae_create_project", {"name": "KAE-Memory", "description": "First."})

        second = dispatch(
            context, "kae_create_project", {"name": "KAE-Memory", "description": "Second."}
        )

        assert second["description"] == "First."

    def test_the_same_name_under_a_different_key_is_a_different_project(
        self, context: tools.ToolContext
    ) -> None:
        first = dispatch(context, "kae_create_project", {"name": "Reporting"})
        second = dispatch(
            context, "kae_create_project", {"name": "Reporting", "key": "reporting-v2"}
        )

        assert second["project_id"] != first["project_id"]


class TestItStartsEmpty:
    def test_a_new_project_reports_that_it_holds_nothing(self, context: tools.ToolContext) -> None:
        """A caller reading created=true must not assume knowledge is present."""

        payload = dispatch(context, "kae_create_project", {"name": "KAE-Memory"})

        assert payload["knowledge_statements"] == 0

    def test_it_confirms_nothing_and_says_so(self, context: tools.ToolContext) -> None:
        payload = dispatch(context, "kae_create_project", {"name": "KAE-Memory"})

        assert any("human act" in step for step in payload["next_steps"])

    def test_the_project_is_immediately_listable(self, context: tools.ToolContext) -> None:
        created = dispatch(context, "kae_create_project", {"name": "KAE-Memory"})

        listed = dispatch(context, "kae_list_projects", {})

        assert created["project_id"] in {p["project_id"] for p in listed["projects"]}


class TestRejectedInput:
    def test_a_missing_name_is_rejected(self, context: tools.ToolContext) -> None:
        with pytest.raises(InvalidArgumentError):
            tools.kae_create_project(context, "")

    def test_a_whitespace_name_is_rejected(self, context: tools.ToolContext) -> None:
        with pytest.raises(InvalidArgumentError):
            tools.kae_create_project(context, "   ")

    def test_a_blank_key_is_rejected_rather_than_derived(self, context: tools.ToolContext) -> None:
        """Silently deriving one would hide that the caller sent something wrong."""

        with pytest.raises(InvalidArgumentError) as raised:
            tools.kae_create_project(context, "KAE-Memory", key="  ")

        assert "omit it" in str(raised.value)


class TestSameNameTwice:
    def test_creating_two_projects_with_one_name_still_succeeds(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        """A derived key is a convenience, so a clash disambiguates.

        create_project has always returned a *new* project. Letting a derived
        key turn that into an error would break callers that never asked for a
        key at all.
        """

        memory = MemoryService(factory)

        first = memory.create_project("Ministry Reporting")
        second = memory.create_project("Ministry Reporting")

        assert first.id != second.id
        assert first.key == "ministry-reporting"
        assert second.key == "ministry-reporting-2"

    def test_an_explicit_key_clash_is_an_error_not_a_rename(
        self, factory: sessionmaker[Session]
    ) -> None:
        """An explicit key is a request for that key.

        Quietly returning a different one would break the idempotence that
        ensure_project builds on top of this clash.
        """

        memory = MemoryService(factory)
        memory.create_project("First", key="shared")

        with pytest.raises(IntegrityError):
            memory.create_project("Second", key="shared")


class TestKeyDerivation:
    def test_punctuation_and_case_collapse(self) -> None:
        assert project_key_from_name("KAE-Memory") == "kae-memory"
        assert project_key_from_name("  My  App! v2 ") == "my-app-v2"

    def test_a_name_with_no_usable_characters_falls_back(self) -> None:
        """A non-Latin name must still produce a key rather than an empty one."""

        derived = project_key_from_name("Проект")

        assert derived.startswith("project-")
        assert len(derived) > len("project-")
