"""Which side of a contradiction is named first, and why it stopped being the UUID.

`EPI-2`, doc 17, `D-148`. Doc 17: conflicts are evaluated by what each source is
capable of establishing, not by which was ingested last. The table itself is
`tests/domain/test_authority.py`.
"""

from __future__ import annotations

from kae_memory.domain.identifiers import KnowledgeItemId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind, KnowledgeSourceType
from kae_memory.domain.reconciliation import EvidenceSnapshot, plan_reconciliation
from kae_memory.domain.relationships import KnowledgeRelation
from kae_memory.domain.synthesis import EvidenceRole

_ALLOWED = "Users may approve their own reports."
_FORBIDDEN = "Users may not approve their own reports."


def _snap(
    item_id: str,
    content: str,
    *source_types: KnowledgeSourceType,
    kind: KnowledgeKind = KnowledgeKind.RULE,
    lifecycle: LifecycleState = LifecycleState.PROPOSED,
) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        KnowledgeItemId(item_id),
        kind.value,
        content,
        lifecycle,
        frozenset(source_types),
    )


def _contradiction(*snapshots: EvidenceSnapshot) -> tuple[str, str]:
    graph = plan_reconciliation(snapshots)
    edges = [edge for edge in graph.edges if edge.type is KnowledgeRelation.CONTRADICTS]
    assert len(edges) == 1, edges
    return str(edges[0].source_id), str(edges[0].target_id)


class TestTheBetterGroundedSideIsNamedFirst:
    def test_a_persons_policy_outranks_a_document_that_merely_mentions_it(self) -> None:
        """A rule claims `normative_policy`, which a project owner settles and an
        imported document only evidences."""

        document = _snap("a", _ALLOWED, KnowledgeSourceType.IMPORTED_DOCUMENT)
        person = _snap("b", _FORBIDDEN, KnowledgeSourceType.USER_STATEMENT)

        assert _contradiction(document, person) == ("b", "a")

    def test_the_identifier_order_does_not_decide_it(self) -> None:
        """The same pair with the authority on the alphabetically-first row.

        Both directions have to be checked, or a test passes on a table that
        does nothing and an ordering that happens to agree with it.
        """

        person = _snap("a", _ALLOWED, KnowledgeSourceType.USER_STATEMENT)
        document = _snap("b", _FORBIDDEN, KnowledgeSourceType.IMPORTED_DOCUMENT)

        assert _contradiction(person, document) == ("a", "b")

    def test_a_recorded_source_outranks_a_row_with_no_provenance(self) -> None:
        """`EPI-5b`: 4,136 live links name no source, and a row that names one is
        better grounded than a row that names nothing."""

        unrecorded = _snap("a", _ALLOWED)
        repository = _snap("b", _FORBIDDEN, KnowledgeSourceType.REPOSITORY)

        assert _contradiction(unrecorded, repository) == ("b", "a")

    def test_kae_inference_never_wins(self) -> None:
        inferred = _snap("a", _ALLOWED, KnowledgeSourceType.KAE_INFERENCE)
        observed = _snap("b", _FORBIDDEN, KnowledgeSourceType.REPOSITORY)

        assert _contradiction(inferred, observed) == ("b", "a")


class TestWhatAuthorityDoesNotOverrule:
    def test_acceptance_still_comes_first(self) -> None:
        """Doc 17 calls acceptance an authority event about the row (`D-148`).

        A source policy able to overrule a person's validation would make
        confirmation advisory, so the validated side leads even though the other
        side's source is authoritative for the scope.
        """

        validated = _snap(
            "a",
            _ALLOWED,
            KnowledgeSourceType.IMPORTED_DOCUMENT,
            lifecycle=LifecycleState.VALIDATED,
        )
        person = _snap("b", _FORBIDDEN, KnowledgeSourceType.USER_STATEMENT)

        assert _contradiction(validated, person) == ("a", "b")

    def test_equally_grounded_rows_keep_the_stable_identifier_order(self) -> None:
        """The tiebreak stays, because two equally grounded rows have no better
        order and an unstable one would stop the pass being idempotent."""

        first = _snap("b", _ALLOWED, KnowledgeSourceType.USER_STATEMENT)
        second = _snap("a", _FORBIDDEN, KnowledgeSourceType.USER_STATEMENT)

        assert _contradiction(first, second) == ("a", "b")

    def test_a_kind_that_claims_nothing_falls_through_to_the_identifier(self) -> None:
        """An assumption asserts nothing a source settles, so authority abstains
        rather than picking a winner from a table that does not apply."""

        person = _snap(
            "b",
            _ALLOWED,
            KnowledgeSourceType.USER_STATEMENT,
            kind=KnowledgeKind.ASSUMPTION,
        )
        inferred = _snap(
            "a",
            _FORBIDDEN,
            KnowledgeSourceType.KAE_INFERENCE,
            kind=KnowledgeKind.ASSUMPTION,
        )

        assert _contradiction(person, inferred) == ("a", "b")

    def test_both_sides_stay_conflicting_whichever_way_the_edge_points(self) -> None:
        """The honest limit on the reader's reach (`D-148`).

        Ordering changes which statement a person is shown first, and nothing
        else: neither side is demoted, and no role is decided by authority.
        """

        document = _snap("a", _ALLOWED, KnowledgeSourceType.IMPORTED_DOCUMENT)
        person = _snap("b", _FORBIDDEN, KnowledgeSourceType.USER_STATEMENT)

        roles = dict(plan_reconciliation((document, person)).roles)
        assert roles[document.id] is EvidenceRole.CONFLICTING
        assert roles[person.id] is EvidenceRole.CONFLICTING
