"""Governed configuration, and what it refuses (N7).

A settings system earns nothing by existing. What it has to be worth is the
three failures it replaces: a number written twice in two adapters, an
environment variable somebody set that nothing reads, and a value out of range
that takes effect anyway.

So the assertions are mostly about refusal and about traceability. The one
positive property — the value is what the file says — is the least interesting
thing here.
"""

from __future__ import annotations

import pytest

from kae_memory.settings import CATALOG, SettingError, Settings, Source, unknown_overrides
from kae_memory.settings.catalog import BY_KEY

PAGE = "response.default_page_size"
CEILING = "response.max_page_size"


class TestTheCommittedDefaultApplies:
    def test_a_clean_environment_gets_the_shipped_value(self) -> None:
        """A deployment that changes nothing gets a working system."""

        resolved = Settings(environ={}).explain(PAGE)

        assert resolved.value == 20
        assert resolved.source is Source.COMMITTED_DEFAULT

    def test_every_catalog_entry_has_a_committed_value(self) -> None:
        """A catalog entry with no value is a contract for something that does
        not exist, and it would fail on whichever call first read it."""

        resolved = {entry.key for entry in Settings(environ={}).explain_all()}

        assert resolved == {setting.key for setting in CATALOG}

    def test_a_missing_default_is_refused_at_construction(self) -> None:
        """At startup, not on first read. The call that first reads a setting
        is reliably the one furthest from anyone who could fix it."""

        with pytest.raises(SettingError, match=r"absent from defaults.toml"):
            Settings(environ={}, defaults={"response": {"default_page_size": 20}})


class TestAnOverrideIsCheckedRatherThanTrusted:
    def test_a_deployment_can_change_it(self) -> None:
        resolved = Settings(environ={"KAE_DEFAULT_PAGE_SIZE": "40"}).explain(PAGE)

        assert resolved.value == 40
        assert resolved.source is Source.ENVIRONMENT

    def test_the_committed_default_is_still_reported(self) -> None:
        """So a diagnostic can show the difference rather than sending a reader
        to look it up."""

        resolved = Settings(environ={"KAE_DEFAULT_PAGE_SIZE": "40"}).explain(PAGE)

        assert resolved.committed_default == 20

    def test_a_non_number_is_refused_by_name(self) -> None:
        """ "KAE_DEFAULT_PAGE_SIZE=lots is not an integer" is actionable;
        "invalid setting" sends someone to read the code."""

        with pytest.raises(SettingError, match=r"KAE_DEFAULT_PAGE_SIZE|response.default_page_size"):
            Settings(environ={"KAE_DEFAULT_PAGE_SIZE": "lots"})

    def test_a_fractional_count_is_refused_rather_than_truncated(self) -> None:
        """A count meant to be fractional is a misunderstanding, not a
        rounding problem."""

        with pytest.raises(SettingError):
            Settings(environ={"KAE_DEFAULT_PAGE_SIZE": "20.5"})

    def test_below_the_minimum_is_refused(self) -> None:
        with pytest.raises(SettingError, match="below the minimum"):
            Settings(environ={"KAE_DEFAULT_PAGE_SIZE": "0"})

    def test_above_the_maximum_is_refused_not_clamped(self) -> None:
        """A caller silently given a different number than they asked for will
        debug everything except the number."""

        with pytest.raises(SettingError, match=r"ceiling|maximum"):
            Settings(environ={"KAE_DEFAULT_PAGE_SIZE": "5000"})

    def test_an_empty_variable_is_not_an_override(self) -> None:
        """A shell that exports everything blank must not silently reconfigure
        the process."""

        resolved = Settings(environ={"KAE_DEFAULT_PAGE_SIZE": "   "}).explain(PAGE)

        assert resolved.value == 20
        assert resolved.source is Source.COMMITTED_DEFAULT

    def test_a_coded_ceiling_cannot_be_crossed(self) -> None:
        """Distinct from a maximum. A maximum says "beyond this is probably a
        mistake"; a ceiling says "beyond this is not ours to allow"."""

        with pytest.raises(SettingError, match="not overridable"):
            Settings(environ={"KAE_MAX_PAGE_SIZE": "100000"})

    def test_the_error_names_the_boundary_and_why(self) -> None:
        with pytest.raises(SettingError) as raised:
            Settings(environ={"KAE_MAX_PAGE_SIZE": "100000"})

        message = str(raised.value)
        assert "1000" in message
        assert "response.max_page_size" in message


class TestEveryValueExplainsItself:
    def test_it_reports_its_unit(self) -> None:
        """Half of all configuration incidents are a unit, and "30" answers
        nothing on its own."""

        assert Settings(environ={}).explain(PAGE).unit == "count"

    def test_it_reports_the_variable_that_overrides_it(self) -> None:
        assert Settings(environ={}).explain(PAGE).env_var == "KAE_DEFAULT_PAGE_SIZE"

    def test_it_reports_when_a_change_takes_effect(self) -> None:
        assert Settings(environ={}).explain(PAGE).reload == "restart"

    def test_the_whole_picture_is_available_at_once(self) -> None:
        """ "Why is the page size 40" is asked at the worst possible moment."""

        described = [entry.as_dict() for entry in Settings(environ={}).explain_all()]

        assert described
        assert all({"key", "value", "source", "unit", "rationale"} <= set(e) for e in described)

    def test_an_unknown_key_names_the_known_ones(self) -> None:
        with pytest.raises(SettingError, match="Known keys"):
            Settings(environ={}).explain("response.page_size_probably")


class TestTheContractIsComplete:
    def test_every_setting_carries_a_rationale(self) -> None:
        """The field most likely to be left empty and the one most needed a
        year later."""

        assert all(setting.rationale.strip() for setting in CATALOG)

    def test_every_setting_declares_a_unit(self) -> None:
        assert all(setting.unit.strip() for setting in CATALOG)

    def test_keys_are_unique(self) -> None:
        """A stable key appearing twice would make a diagnostic ambiguous about
        which contract an operator's runbook refers to."""

        assert len(BY_KEY) == len(CATALOG)

    def test_no_setting_names_a_secret(self) -> None:
        """A committed defaults file is read by everyone who clones the
        repository. Connection strings and tokens have no safe default and must
        never acquire one here."""

        forbidden = ("token", "secret", "password", "url", "credential")
        assert not [
            setting.key
            for setting in CATALOG
            if any(word in setting.key.lower() for word in forbidden)
        ]


class TestTheAuditCatchesTheDeadVariable:
    def test_a_variable_nothing_reads_is_reported(self) -> None:
        """Worse than no variable: someone sets it, watches nothing change, and
        concludes the setting does not work."""

        assert unknown_overrides({"KAE_PAGE_SIZE": "40"}) == ("KAE_PAGE_SIZE",)

    def test_a_governed_variable_is_not_reported(self) -> None:
        assert unknown_overrides({"KAE_DEFAULT_PAGE_SIZE": "40"}) == ()

    def test_a_known_ungoverned_variable_is_not_reported(self) -> None:
        """Secrets, deployment facts, and knobs not yet migrated. The list is
        the honest record of the third category rather than a claim that the
        first slice covered everything."""

        assert unknown_overrides({"KAE_DATABASE_URL": "postgresql://x"}) == ()

    def test_unrelated_variables_are_ignored(self) -> None:
        assert unknown_overrides({"PATH": "/usr/bin", "AWS_REGION": "us-east-1"}) == ()


class TestOneNumberReachesBothAdapters:
    def test_the_http_page_bound_is_the_mcp_one(self) -> None:
        """The defect this slice was chosen to find. These were `100` written
        twice, in two adapters, with the same docstring, and nothing would have
        noticed them diverging."""

        from kae_memory.api.routers.pipeline import MAX_PAGE
        from kae_memory.mcp.response_policy import MAX_PAGE_SIZE

        assert MAX_PAGE is MAX_PAGE_SIZE

    def test_both_come_from_the_governed_setting(self) -> None:
        from kae_memory.mcp.response_policy import MAX_PAGE_SIZE

        assert Settings(environ={}).value(CEILING) == MAX_PAGE_SIZE

    def test_the_clarification_limit_is_governed(self) -> None:
        from kae_memory.mcp.tools import CLARIFICATION_LIMIT

        assert Settings(environ={}).value("clarifications.default_limit") == CLARIFICATION_LIMIT
