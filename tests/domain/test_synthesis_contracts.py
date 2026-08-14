"""Evidence, synthesized objects, and attention are three contracts, not one."""

from datetime import UTC, datetime

import pytest

from kae_memory.domain import (
    AttentionItem,
    AttentionItemId,
    AttentionKind,
    AttentionStatus,
    Authority,
    DomainInvariantError,
    InvalidLifecycleTransitionError,
    ProjectId,
    SynthesizedLifecycle,
    SynthesizedObject,
    SynthesizedObjectId,
)
from kae_memory.domain.synthesis import HOT_EVIDENCE, OPEN_ATTENTION, EvidenceRole

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _object(
    *,
    lifecycle: SynthesizedLifecycle = SynthesizedLifecycle.WORKING,
    authority: Authority = Authority.WORKING_MODEL,
    domain: str = "goal",
) -> SynthesizedObject:
    return SynthesizedObject(
        id=SynthesizedObjectId("11111111-1111-1111-1111-111111111111"),
        project_id=ProjectId("22222222-2222-2222-2222-222222222222"),
        domain=domain,
        identity_key="planning-expertise",
        title="The plan is ready for development",
        statement="Produce a development-ready plan.",
        lifecycle=lifecycle,
        authority=authority,
        created_at=NOW,
        updated_at=NOW,
    )


def test_human_authority_cannot_sit_on_a_working_lifecycle() -> None:
    with pytest.raises(DomainInvariantError):
        _object(authority=Authority.HUMAN, lifecycle=SynthesizedLifecycle.WORKING)


def test_authoritative_lifecycle_requires_human_authority() -> None:
    with pytest.raises(DomainInvariantError):
        _object(
            lifecycle=SynthesizedLifecycle.AUTHORITATIVE,
            authority=Authority.WORKING_MODEL,
        )


def test_working_update_refuses_a_human_authoritative_object() -> None:
    obj = _object(
        lifecycle=SynthesizedLifecycle.AUTHORITATIVE,
        authority=Authority.HUMAN,
    )

    with pytest.raises(DomainInvariantError, match="human-authoritative"):
        obj.with_working_update("other", "other statement")


def test_human_correction_becomes_authoritative() -> None:
    corrected = _object().with_human_correction("Settled title", "Settled statement")

    assert corrected.authority is Authority.HUMAN
    assert corrected.lifecycle is SynthesizedLifecycle.AUTHORITATIVE
    assert corrected.revision == 2
    assert _object().revision == 1


def test_attention_cannot_reopen_a_resolved_item() -> None:
    item = AttentionItem(
        id=AttentionItemId("33333333-3333-3333-3333-333333333333"),
        project_id=ProjectId("22222222-2222-2222-2222-222222222222"),
        kind=AttentionKind.DECISION,
        title="Choose the collaboration MVP",
        explanation="Two candidates remain.",
        status=AttentionStatus.RESOLVED,
    )

    with pytest.raises(InvalidLifecycleTransitionError):
        item.transition_to(AttentionStatus.OPEN)


def test_deferred_attention_still_occupies_the_queue() -> None:
    assert AttentionStatus.DEFERRED in OPEN_ATTENTION
    assert AttentionStatus.RESOLVED not in OPEN_ATTENTION


def test_noise_is_not_hot_evidence() -> None:
    assert EvidenceRole.NOISE not in HOT_EVIDENCE
    assert EvidenceRole.ACTIVE in HOT_EVIDENCE


def test_synthesized_object_rejects_an_unknown_domain() -> None:
    with pytest.raises(DomainInvariantError, match="unknown synthesized domain"):
        _object(domain="theme")
