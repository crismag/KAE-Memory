"""What a project is configured as, distinct from what it is known to be (N26).

The problem this solves is narrow and concrete: **publication must not search
natural-language knowledge at runtime to decide where to write files.** "The
project uses crismag/KAE-Studio" is a perfectly good knowledge statement, and
resolving a publication destination by reading it would mean a sentence someone
confirmed for one reason silently routing bytes for another.

So there are two records. Knowledge says what is true about the project.
Configuration says what the project is set up to do. A value may be *derived*
from confirmed knowledge, and when it is, that derivation is recorded — but it
is derived once, deliberately, into a validated field, not searched for at the
moment a file is being written.

**A project must be creatable with almost none of this populated.**
`primary_repository` is unknown for an idea; `default_publication_target` stays
unknown until someone publishes something. Every field defaults to unknown and
an unknown field blocks only the operation that actually needs it.

**No credentials, at any state.** A field whose name suggests one is refused
here rather than filtered later, because a secret that reaches this record has
already been written down somewhere it can be read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .errors import DomainInvariantError
from .identifiers import ProjectId
from .setup import IN_USE, NEVER_INFERRED, ValueState


class ConfigurationError(DomainInvariantError):
    """A configuration field or value is not one this model permits."""


@dataclass(frozen=True, slots=True)
class ConfiguredValue:
    """One field, its value, and how it came to have one.

    `state` carries as much meaning as `value`. A field holding
    `"crismag/KAE-Studio"` as `confirmed` and the same string as `suggested` are
    different situations, and only one of them routes a publication.
    """

    field_name: str
    value: str | None = None
    state: ValueState = ValueState.UNKNOWN
    evidence: str = ""
    """Where the value came from: a person, a derivation, an inherited default.
    Required for anything KAE worked out itself."""

    derived_from_knowledge_id: str | None = None
    """The confirmed statement this was derived from, if it was.

    Recorded so a reader can see the derivation happened **once, deliberately**,
    rather than a publication resolving its destination by reading prose.
    """

    confirmed_by: str | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.field_name.strip():
            raise ConfigurationError("a configured value needs a field name")
        ensure_not_secret(self.field_name)
        if self.state in IN_USE and not (self.value or "").strip():
            raise ConfigurationError(
                f"{self.field_name} is {self.state.value} with no value. A field "
                f"in use and empty is a configuration that will fail at the "
                f"moment it is needed."
            )
        if self.state in {ValueState.INFERRED, ValueState.SUGGESTED} and not self.evidence.strip():
            raise ConfigurationError(
                f"{self.field_name} was {self.state.value} with no evidence. "
                f"Nobody can judge a value they cannot trace."
            )
        if self.state is ValueState.CONFIRMED and not (self.confirmed_by or "").strip():
            raise ConfigurationError(
                f"{self.field_name} is confirmed by nobody. Confirmation is an act "
                f"a person performs (FR-005), and an unattributed one records that "
                f"the system agreed with itself."
            )

    @property
    def in_use(self) -> bool:
        """Whether this value actually takes effect.

        A suggestion does not. That is the entire reason `suggested` exists as
        a separate state: it is what KAE would choose, not what it chose.
        """

        return self.state in IN_USE

    @property
    def known(self) -> bool:
        return self.state is not ValueState.UNKNOWN


def ensure_not_secret(field_name: str) -> None:
    """Refuse a field that names a credential.

    Here rather than at the boundary that writes it, because every boundary
    would have to remember. A secret that reached this record has already been
    written somewhere readable, and removing it afterwards does not unwrite it.
    """

    lowered = field_name.lower()
    if any(fragment in lowered for fragment in NEVER_INFERRED):
        raise ConfigurationError(
            f"{field_name} names a credential or an authorisation, which never "
            f"belongs in project configuration. Connections and their "
            f"authorisation live in the runtime layer (N28)."
        )


KNOWN_FIELDS: frozenset[str] = frozenset(
    {
        "primary_repository",
        "primary_branch",
        "default_publication_target",
        "deliverable_format",
        "working_directory",
        "project_kind",
    }
)
"""The fields this version understands.

Written out so that an unrecognised field is a **refusal rather than a silent
acceptance**: a caller who misspells `primary_repository` must not create a
second field that configures nothing and looks configured.

Small on purpose. Each entry arrived with something that reads it; a field
added ahead of its reader is the "exists with no caller" pattern this
repository has shipped three times.
"""


@dataclass(frozen=True, slots=True)
class ProjectConfiguration:
    """One project's typed configuration, every field optional.

    Creatable empty, and that is the ordinary case rather than a degenerate
    one. An idea described in a sentence has no repository, no branch, and no
    publication target, and nothing about it is wrong.
    """

    project_id: ProjectId
    values: Mapping[str, ConfiguredValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = sorted(set(self.values) - KNOWN_FIELDS)
        if unknown:
            raise ConfigurationError(
                f"unrecognised configuration field(s) {unknown}. This version "
                f"understands: {', '.join(sorted(KNOWN_FIELDS))}. A misspelled "
                f"field would configure nothing and look configured."
            )
        for name, value in self.values.items():
            if value.field_name != name:
                raise ConfigurationError(
                    f"configuration is keyed {name!r} and holds a value for {value.field_name!r}"
                )

    def get(self, field_name: str) -> ConfiguredValue:
        """Return one field, unknown if it has never been set.

        Never raises for an absent field: absence is the normal state, and a
        caller forced to handle it separately would write the same three lines
        everywhere.
        """

        if field_name not in KNOWN_FIELDS:
            raise ConfigurationError(
                f"unknown configuration field {field_name!r}. Known: "
                f"{', '.join(sorted(KNOWN_FIELDS))}"
            )
        return self.values.get(field_name, ConfiguredValue(field_name=field_name))

    def effective(self, field_name: str) -> str | None:
        """Return the value that actually takes effect, or `None`.

        A suggestion returns `None`. A caller asking what a project is
        configured as must not receive what it might be configured as.
        """

        value = self.get(field_name)
        return value.value if value.in_use else None

    def unknown_fields(self) -> tuple[str, ...]:
        """Fields nothing has established. Frequently most of them."""

        return tuple(sorted(name for name in KNOWN_FIELDS if not self.get(name).known))

    def disclosures(self) -> tuple[ConfiguredValue, ...]:
        """Values in use that KAE worked out rather than a person supplying.

        The same rule as an assumption: a reader who cannot tell what was
        derived from what was decided will read the first as the second.
        """

        return tuple(
            value
            for value in self.values.values()
            if value.in_use and value.state is not ValueState.CONFIRMED
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            name: {
                "value": value.value,
                "state": value.state.value,
                "in_use": value.in_use,
                "evidence": value.evidence,
                "derived_from_knowledge_id": value.derived_from_knowledge_id,
                "confirmed_by": value.confirmed_by,
            }
            for name, value in sorted(self.values.items())
        }
