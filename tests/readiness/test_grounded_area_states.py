"""`ADR-0008`'s ladder: what an area says, read from where its claims came from.

The ADR's rule is that readiness derives from externally grounded knowledge and
not from the quantity of KAE-generated records. Before `EPI-5b` an area had one
word for two very different situations — a project that had read a repository
and one that had only talked to itself both reported `partial`.

The three properties these tests hold, and the reason each is here:

* a grounded source is what moves an area up, and quantity never is;
* `D-107` moved the vocabulary and deliberately left the calibration alone, so
  **no project's percentage may change** — the score guard below is the whole of
  that promise and is the test to look at first if a number moves;
* an area that is better grounded is still not finished, so it must keep saying
  so.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from kae_memory.application.readiness_service import evaluate_area, score_areas
from kae_memory.domain.identifiers import AgentId, ExecutionId, KnowledgeItemId, ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, KnowledgeVersion, Provenance
from kae_memory.domain.readiness import (
    UNFINISHED_STATES,
    AreaDefinition,
    AreaState,
    Claim,
    credit_for,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
PROJECT = ProjectId("11111111-1111-1111-1111-111111111111")

REQUIREMENTS = AreaDefinition(
    key="functional_requirements",
    name="Functional requirements",
    weight=2.0,
    kinds=(KnowledgeKind.REQUIREMENT,),
    minimum_confirmed=3,
)

DIVIDED = AreaDefinition(
    key="problem_and_value",
    name="Problem and value proposition",
    weight=1.5,
    kinds=(KnowledgeKind.GOAL,),
    claims=(Claim("problem_statement", "What hurts"), Claim("value_proposition", "Why")),
)


def item(
    kind: str = "requirement",
    lifecycle: LifecycleState = LifecycleState.PROPOSED,
) -> KnowledgeItem:
    return KnowledgeItem(
        id=KnowledgeItemId(str(uuid4())),
        project_id=PROJECT,
        kind=kind,
        versions=(
            KnowledgeVersion(
                number=1,
                content=f"A {kind} claim.",
                provenance=Provenance(
                    source="test",
                    actor_id=AgentId("requirements"),
                    execution_id=ExecutionId(str(uuid4())),
                    recorded_at=NOW,
                ),
                created_at=NOW,
            ),
        ),
        lifecycle=lifecycle,
    )


def grounding(*pairs: tuple[KnowledgeItem, str]) -> dict[str, frozenset[str]]:
    """Return the per-item source kinds the calculator reads."""

    return {str(known.id): frozenset({kind}) for known, kind in pairs}


class TestAGroundedSourceIsWhatRaisesAnArea:
    """The state comes from *what kind of* source, never from how many rows."""

    def test_only_kae_inference_stays_partial(self) -> None:
        """The ADR's *"proposal — not evidence"*, which had nowhere to live."""

        derived = item()

        result = evaluate_area(
            REQUIREMENTS,
            [derived],
            frozenset(),
            source_types_by_item=grounding((derived, "kae_inference")),
        )

        assert result.state is AreaState.PARTIAL

    @pytest.mark.parametrize("source_type", ["repository", "user_statement", "imported_document"])
    def test_each_source_outside_kae_reaches_evidenced(self, source_type: str) -> None:
        """All three rows of `ADR-0008`'s table ground a statement, not just one."""

        grounded = item()

        result = evaluate_area(
            REQUIREMENTS,
            [grounded],
            frozenset(),
            source_types_by_item=grounding((grounded, source_type)),
        )

        assert result.state is AreaState.EVIDENCED

    def test_kae_reading_a_grounded_source_reaches_interpreted(self) -> None:
        read = item()
        derived = item()

        result = evaluate_area(
            REQUIREMENTS,
            [read, derived],
            frozenset(),
            source_types_by_item=grounding((read, "repository"), (derived, "kae_inference")),
        )

        assert result.state is AreaState.INTERPRETED

    def test_generating_more_candidates_never_raises_the_state(self) -> None:
        """The property the whole model exists for, restated on the new ladder."""

        one = item()
        alone = evaluate_area(
            REQUIREMENTS,
            [one],
            frozenset(),
            source_types_by_item=grounding((one, "kae_inference")),
        )

        many = [item() for _ in range(50)]
        crowded = evaluate_area(
            REQUIREMENTS,
            many,
            frozenset(),
            source_types_by_item={str(each.id): frozenset({"kae_inference"}) for each in many},
        )

        assert alone.state is AreaState.PARTIAL
        assert crowded.state is AreaState.PARTIAL
        assert crowded.credit == alone.credit

    def test_a_statement_with_no_recorded_source_reads_as_ungrounded(self) -> None:
        """Every row written before `EPI-5a` carries ``NULL``.

        Reading absence as grounded would promote every area in every database
        that existed before the column was fed, on the strength of a field
        nothing had ever written.
        """

        result = evaluate_area(REQUIREMENTS, [item()], frozenset(), source_types_by_item={})

        assert result.state is AreaState.PARTIAL

    def test_a_divided_area_climbs_the_same_ladder(self) -> None:
        """`problem_and_value` is the only divided area, and it is not exempt."""

        read = item("goal")

        result = evaluate_area(
            DIVIDED,
            [read],
            frozenset(),
            source_types_by_item=grounding((read, "user_statement")),
        )

        assert result.state is AreaState.EVIDENCED


class TestConfirmationStillOutranksGrounding:
    """`SUFFICIENT` is the ADR's `confirmed`, and grounding is not a shortcut."""

    def test_grounded_but_unconfirmed_does_not_become_sufficient(self) -> None:
        proposed = [item() for _ in range(9)]

        result = evaluate_area(
            REQUIREMENTS,
            proposed,
            frozenset(),
            source_types_by_item={str(each.id): frozenset({"repository"}) for each in proposed},
        )

        assert result.state is AreaState.EVIDENCED
        assert result.confirmed_count == 0

    def test_confirmed_knowledge_is_sufficient_whatever_its_source(self) -> None:
        """Confirmation is a person's act; it does not re-derive from provenance."""

        confirmed = [item(lifecycle=LifecycleState.VALIDATED) for _ in range(3)]

        result = evaluate_area(
            REQUIREMENTS,
            confirmed,
            frozenset(),
            source_types_by_item={str(each.id): frozenset({"kae_inference"}) for each in confirmed},
        )

        assert result.state is AreaState.SUFFICIENT

    def test_an_evidenced_area_is_still_unfinished(self) -> None:
        """The rung is better grounded and the work is not done.

        `UNFINISHED_STATES` exists so that adding a rung cannot quietly stop a
        project being told an area needs attention — the shape of `D-27`.
        """

        assert AreaState.EVIDENCED in UNFINISHED_STATES
        assert AreaState.INTERPRETED in UNFINISHED_STATES
        assert AreaState.SUFFICIENT not in UNFINISHED_STATES
        assert AreaState.NOT_APPLICABLE not in UNFINISHED_STATES


class TestTheVocabularyMovedAndTheNumberDidNot:
    """`D-107`'s promise, and the only test that has to fail if it is broken.

    `ADR-0008` puts weights out of scope: *"changing the semantics and the
    calibration at once would make the result unattributable to either"*.
    Credit-per-state is calibration, so the new tiers take exactly the credit
    the state they replace already carried.
    """

    @pytest.mark.parametrize("state", [AreaState.EVIDENCED, AreaState.INTERPRETED])
    def test_the_new_tiers_carry_exactly_the_credit_partial_did(self, state: AreaState) -> None:
        assert credit_for(state) == credit_for(AreaState.PARTIAL)

    def test_the_same_knowledge_scores_the_same_as_before_the_ladder(self) -> None:
        """A project scored with provenance and without must land on one number."""

        read = item()
        derived = item()
        items = [read, derived]

        before = evaluate_area(REQUIREMENTS, items, frozenset())
        after = evaluate_area(
            REQUIREMENTS,
            items,
            frozenset(),
            source_types_by_item=grounding((read, "repository"), (derived, "kae_inference")),
        )

        assert before.state is AreaState.PARTIAL
        assert after.state is AreaState.INTERPRETED
        assert score_areas([after]) == score_areas([before])
