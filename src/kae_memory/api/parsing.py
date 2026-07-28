"""Parsing request values into domain enums.

A client that sends ``"reviewer"`` instead of ``"review"`` should learn the
permitted set from the response. Rejecting with the valid values costs nothing
and removes a whole class of guesswork from integrating with this API.
"""

from enum import Enum

from .errors import ApiError


def parse_enum[EnumT: Enum](kind: type[EnumT], value: str, field: str) -> EnumT:
    """Return the enum member for ``value``, or raise a 422 listing the valid ones."""

    try:
        return kind(value)
    except ValueError as error:
        raise ApiError(
            422,
            f"invalid_{field}",
            f"Unknown {field}: {value!r}.",
            {"permitted": sorted(str(member.value) for member in kind)},
        ) from error
