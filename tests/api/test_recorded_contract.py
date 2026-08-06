"""The recorded HTTP contract matches the one the application serves (N9).

This guard lived in CI, generated a TypeScript client, and diffed the result.
The client is gone with the embedded frontend. The guard is not, because what it
actually caught had nothing to do with React: **a backend contract change that
nobody carried into the recorded document.**

Here rather than in CI, so it fails in the command a developer already runs
rather than fifteen minutes later in a job needing a Node toolchain.

It is not a schema review. A route added deliberately updates the document in
the same commit; the failure it exists to produce is the *accidental* change —
a parameter renamed, a field dropped, a status code moved — noticed by whoever
made it rather than by whoever integrates against it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.api import create_app

RECORDED = Path(__file__).resolve().parents[2] / "specifications" / "openapi.json"
REGENERATE = "uv run python scripts/development/dump-openapi.py"


@pytest.fixture(scope="module")
def served() -> dict[str, Any]:
    """The document the application would serve right now.

    A lazily-connected engine: `create_app` stores the factory and opens nothing
    until a request arrives, and none does here — so this needs no database and
    runs in the offline suite.
    """

    factory = sessionmaker(create_engine("postgresql+psycopg://unused@localhost/unused"))
    return create_app(factory).openapi()


@pytest.fixture(scope="module")
def recorded() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(RECORDED.read_text())
    return document


class TestTheRecordedDocumentIsCurrent:
    def test_every_served_path_is_recorded(
        self, served: dict[str, Any], recorded: dict[str, Any]
    ) -> None:
        """A route nobody recorded is a route no integrator knows exists."""

        missing = sorted(set(served["paths"]) - set(recorded["paths"]))

        assert not missing, f"served but not recorded: {missing}. Run: {REGENERATE}"

    def test_every_recorded_path_is_still_served(
        self, served: dict[str, Any], recorded: dict[str, Any]
    ) -> None:
        """The direction that matters more. A path in the document and not in
        the application is a promise the deployment does not keep."""

        removed = sorted(set(recorded["paths"]) - set(served["paths"]))

        assert not removed, f"recorded but no longer served: {removed}. Run: {REGENERATE}"

    def test_the_document_matches_exactly(
        self, served: dict[str, Any], recorded: dict[str, Any]
    ) -> None:
        """Whole-document, not path names. The changes worth catching are the
        quiet ones — a parameter renamed, a field dropped, a status moved — and
        none of them changes the set of paths."""

        assert served == recorded, (
            f"the recorded contract is stale. Run: {REGENERATE}, review the diff, "
            f"and commit it with the change that caused it."
        )


class TestTheDocumentIsWorthRecording:
    def test_it_describes_a_real_surface(self, recorded: dict[str, Any]) -> None:
        """Guards against the failure where both sides agree on nothing: an
        empty document matches an empty application perfectly."""

        assert len(recorded["paths"]) > 20

    def test_it_is_stored_deterministically(self) -> None:
        """Sorted and indented, so a diff shows what changed rather than how
        the serialiser felt. An unsorted document produces review noise that
        trains people to skim exactly the diff this guard exists to surface."""

        text = RECORDED.read_text()

        assert text.endswith("\n")
        assert json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n" == text

    def test_it_lives_outside_any_presentation_directory(self) -> None:
        """It was under `frontend/`, which is why it read as frontend
        infrastructure and nearly left with it (N9)."""

        assert RECORDED.parent.name == "specifications"
