"""Response conventions, and the floor they may never go under.

The integrity floor is the reason this module exists as a registry rather than a
paragraph. A rule in prose is only as strong as whoever is reviewing; a registry
with a test is a guarantee.
"""

from __future__ import annotations

import pytest

from kae_memory.mcp.response_policy import (
    INTEGRITY_FIELDS,
    PROFILES,
    SERVER_MAXIMUMS,
    SHORT_FORMS,
    DetailLevel,
    InvalidPolicyError,
    ProseLevel,
    ResponsePolicy,
    ResponseProfile,
    clamp,
    from_arguments,
    from_environment,
    includes,
    project,
    within_budget,
)

FIELD_LEVELS = {
    "sections": DetailLevel.STANDARD,
    "explanation": DetailLevel.DIAGNOSTIC,
}

PAYLOAD = {
    "project": {"name": "KAE-Memory"},
    "sections": [{"area": "problem_and_value"}],
    "explanation": {"earned_weight": 7.0},
    "warnings": [
        "Nothing matched. This is a result, not a failure: no stored "
        "knowledge met the relevance threshold for this query."
    ],
    "search_mode": "lexical",
}


class TestIntegrityFloor:
    def test_integrity_fields_survive_the_lowest_detail(self) -> None:
        """The load-bearing guarantee."""

        result = project(PAYLOAD, PROFILES[ResponseProfile.ECONOMY], FIELD_LEVELS)

        assert result["search_mode"] == "lexical"
        assert result["warnings"]

    def test_integrity_fields_survive_a_field_level_that_would_drop_them(self) -> None:
        """A field map must not be able to override the floor.

        Someone adding `warnings: DIAGNOSTIC` to a tool's map would otherwise
        make the cheapest profile the least honest one.
        """

        hostile = {
            **FIELD_LEVELS,
            "warnings": DetailLevel.DIAGNOSTIC,
            "search_mode": DetailLevel.DIAGNOSTIC,
        }

        result = project(PAYLOAD, ResponsePolicy(detail=DetailLevel.SUMMARY), hostile)

        assert "warnings" in result
        assert "search_mode" in result

    def test_the_floor_names_what_it_protects(self) -> None:
        for field in ("warnings", "guidance", "caveat", "scope_note", "truncation"):
            assert field in INTEGRITY_FIELDS


class TestDetailLevels:
    def test_summary_omits_standard_and_diagnostic_fields(self) -> None:
        result = project(PAYLOAD, ResponsePolicy(detail=DetailLevel.SUMMARY), FIELD_LEVELS)

        assert "sections" not in result
        assert "explanation" not in result
        assert result["project"] == {"name": "KAE-Memory"}

    def test_standard_adds_sections_but_not_the_arithmetic(self) -> None:
        result = project(PAYLOAD, ResponsePolicy(detail=DetailLevel.STANDARD), FIELD_LEVELS)

        assert "sections" in result
        assert "explanation" not in result

    def test_diagnostic_carries_everything(self) -> None:
        result = project(PAYLOAD, ResponsePolicy(detail=DetailLevel.DIAGNOSTIC), FIELD_LEVELS)

        assert "sections" in result
        assert "explanation" in result
        assert "truncation" not in result

    def test_levels_are_ordered(self) -> None:
        assert includes(DetailLevel.DIAGNOSTIC, DetailLevel.SUMMARY)
        assert not includes(DetailLevel.SUMMARY, DetailLevel.STANDARD)

    def test_an_unmapped_field_is_always_included(self) -> None:
        result = project({"anything": 1}, PROFILES[ResponseProfile.ECONOMY], {})

        assert result["anything"] == 1


class TestDroppingIsReported:
    def test_dropped_fields_are_named(self) -> None:
        """A silently omitted section is indistinguishable from an empty one."""

        result = project(PAYLOAD, ResponsePolicy(detail=DetailLevel.SUMMARY), FIELD_LEVELS)

        assert result["truncation"]["applied"] is True
        assert result["truncation"]["dropped"] == ["explanation", "sections"]
        assert "detail=diagnostic" in result["truncation"]["retrieve_with"]

    def test_the_resolved_policy_ships_with_the_response(self) -> None:
        """A custom profile is irreproducible unless the response says what ran."""

        result = project(PAYLOAD, PROFILES[ResponseProfile.ECONOMY], FIELD_LEVELS)

        assert result["response_policy"]["profile"] == "economy"
        assert result["response_policy"]["detail"] == "summary"


class TestProse:
    def test_registered_statements_shorten(self) -> None:
        result = project(PAYLOAD, ResponsePolicy(prose=ProseLevel.NONE), FIELD_LEVELS)

        assert result["warnings"] == ["No match; nothing met the threshold."]

    def test_standard_prose_leaves_wording_alone(self) -> None:
        result = project(PAYLOAD, ResponsePolicy(prose=ProseLevel.STANDARD), FIELD_LEVELS)

        assert result["warnings"] == PAYLOAD["warnings"]

    def test_an_unregistered_string_is_never_guessed_at(self) -> None:
        """Runtime summarisation would make the guarantee non-deterministic."""

        payload = {"warnings": ["Something nobody registered a short form for."]}

        result = project(payload, ResponsePolicy(prose=ProseLevel.NONE), {})

        assert result["warnings"] == payload["warnings"]

    def test_shortening_never_empties_a_statement(self) -> None:
        for full, short in SHORT_FORMS.items():
            assert short.strip()
            assert len(short) < len(full)


class TestResolution:
    def test_profiles_resolve_to_explicit_values(self) -> None:
        economy = PROFILES[ResponseProfile.ECONOMY]

        assert economy.detail is DetailLevel.SUMMARY
        assert economy.max_output_tokens == 800

    def test_regular_is_the_default(self) -> None:
        assert from_environment({}).profile is ResponseProfile.REGULAR

    def test_environment_overrides_apply(self) -> None:
        policy = from_environment({"KAE_MCP_DETAIL": "diagnostic", "KAE_MCP_MAX_TOKENS": "900"})

        assert policy.detail is DetailLevel.DIAGNOSTIC
        assert policy.max_output_tokens == 900

    def test_per_request_overrides_beat_the_deployment_default(self) -> None:
        base = from_environment({"KAE_MCP_PROFILE": "economy"})

        policy = from_arguments({"detail": "diagnostic"}, base)

        assert policy.detail is DetailLevel.DIAGNOSTIC
        assert policy.profile is ResponseProfile.CUSTOM

    def test_a_request_may_ask_for_less_than_the_ceiling(self) -> None:
        assert clamp(ResponsePolicy(max_output_tokens=100)).max_output_tokens == 100

    def test_a_request_may_not_exceed_the_ceiling(self) -> None:
        """A client may request less, never more."""

        policy = from_arguments({"max_output_tokens": 999_999}, PROFILES[ResponseProfile.REGULAR])

        assert policy.max_output_tokens == SERVER_MAXIMUMS.max_output_tokens

    def test_an_unknown_profile_is_rejected(self) -> None:
        with pytest.raises(InvalidPolicyError) as raised:
            from_arguments({"profile": "luxury"}, PROFILES[ResponseProfile.REGULAR])

        assert "Valid:" in str(raised.value)

    def test_an_unknown_detail_level_is_rejected(self) -> None:
        """Silently ignoring one lets a caller believe a budget applied."""

        with pytest.raises(InvalidPolicyError):
            from_arguments({"detail": "full"}, PROFILES[ResponseProfile.REGULAR])

    def test_a_zero_limit_is_rejected(self) -> None:
        with pytest.raises(InvalidPolicyError):
            clamp(ResponsePolicy(max_entities=0))


class TestBudget:
    def test_a_small_payload_is_within_an_ordinary_budget(self) -> None:
        assert within_budget(PAYLOAD, PROFILES[ResponseProfile.REGULAR])

    def test_a_large_payload_exceeds_a_tight_one(self) -> None:
        payload = {"sections": [{"text": "x" * 200} for _ in range(200)]}

        assert not within_budget(payload, PROFILES[ResponseProfile.ECONOMY])

    def test_no_budget_means_no_ceiling(self) -> None:
        assert within_budget({"a": "x" * 100_000}, ResponsePolicy(max_output_tokens=None))
