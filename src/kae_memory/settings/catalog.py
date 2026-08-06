"""What each governed setting is, separately from what it currently is (N7).

A setting has a value and a *contract*: what it means, what units it is in, what
range is sane, who may override it, and what happens if they do. The value lives
in `defaults.toml` and may be overridden per deployment; the contract lives here
and may not. Splitting them is what makes an override checkable — an
environment variable resolved against nothing is a string somebody typed.

**Deliberately small.** This is not a policy framework and the focus file rules
one out. Every entry here is a value that changes behaviour a caller can
observe, and the first slice is the one already covered by contract tests:
pagination and response limits.

What is **not** here, and why:

*Protocol and mathematical constants* stay named near the code that uses them.
`MAX_TOKENS` for chunking is a property of the tokeniser, not a knob.

*Absolute security ceilings* stay in code. `MAX_BODY_BYTES` exists to stop a
process reading a request it cannot afford, and a deployment able to raise it
has removed the protection rather than tuned it.

*Secrets and provider selection* stay in the environment and never appear in a
committed defaults file. `KAE_DATABASE_URL` is not a product default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Scope(StrEnum):
    """Who a setting belongs to."""

    PRODUCT = "product"
    """A safe default that ships with KAE and suits most deployments."""

    DEPLOYMENT = "deployment"
    """A value one installation is expected to choose for itself."""


class Reload(StrEnum):
    """When a change takes effect."""

    RESTART = "restart"
    PER_CALL = "per_call"


class Source(StrEnum):
    """Where an effective value came from.

    Reported rather than inferred. "Why is the page size 40" is a question a
    deployment asks at the worst possible moment, and an answer that requires
    reading three files is not an answer.
    """

    CODED_CEILING = "coded_ceiling"
    ENVIRONMENT = "environment"
    COMMITTED_DEFAULT = "committed_default"


class SettingError(RuntimeError):
    """A setting is missing, mistyped, or outside what it is allowed to be."""


@dataclass(frozen=True, slots=True)
class Setting:
    """The contract for one governed value.

    Every field is required except the bounds, because a setting whose rationale
    or unit nobody wrote down is one nobody can safely change — which is the
    state this target exists to leave behind.
    """

    key: str
    """Stable identifier, dotted. Stable is the point: it appears in
    diagnostics and in a deployment's notes, and renaming one silently changes
    what an operator's runbook refers to."""

    kind: type
    unit: str
    """`count`, `seconds`, `bytes`, `percent`, or `none`. Written out because
    "30" answers nothing and half of all configuration incidents are a unit."""

    rationale: str
    """Why this value rather than another. The field most likely to be left
    empty and the one most needed a year later."""

    scope: Scope
    reload: Reload
    env_var: str | None = None
    """The deployment override, or `None` where there is none. Absent rather
    than ignored: a variable nothing reads is worse than no variable, because
    someone will set it and believe it took effect."""

    minimum: float | None = None
    maximum: float | None = None
    """The range an override must fall within. Exceeding it is **refused, not
    clamped** — a caller silently given a different number than they asked for
    will debug everything except the number."""

    ceiling: float | None = None
    """An absolute boundary no override may cross, distinct from `maximum`.

    `maximum` says "beyond this is probably a mistake". A ceiling says "beyond
    this is not ours to allow", and it is the first precedence layer for that
    reason.
    """

    implication: str = ""
    """Any security, cost, or performance consequence of changing it."""

    @property
    def overridable(self) -> bool:
        return self.env_var is not None


CATALOG: tuple[Setting, ...] = (
    Setting(
        key="response.default_page_size",
        kind=int,
        unit="count",
        rationale=(
            "Large enough to answer most questions in one call, small enough "
            "that a project with hundreds of statements does not arrive as a "
            "single unreadable response."
        ),
        scope=Scope.PRODUCT,
        reload=Reload.RESTART,
        env_var="KAE_DEFAULT_PAGE_SIZE",
        minimum=1,
        maximum=100,
        ceiling=100,
        implication="A larger page costs tokens on every read that does not name a limit.",
    ),
    Setting(
        key="response.max_page_size",
        kind=int,
        unit="count",
        rationale=(
            "The ceiling a caller cannot raise. A page is a budget, not a "
            "suggestion, and an unbounded page turns one careless call into "
            "the whole project."
        ),
        scope=Scope.PRODUCT,
        reload=Reload.RESTART,
        env_var="KAE_MAX_PAGE_SIZE",
        minimum=1,
        maximum=1000,
        ceiling=1000,
        implication=(
            "Raising this raises the largest response any single call can "
            "produce, on both adapters at once."
        ),
    ),
    Setting(
        key="clarifications.default_limit",
        kind=int,
        unit="count",
        rationale=(
            "A gap list is a work queue, and handing back forty at once "
            "produces neither a review nor a plan. A default rather than a "
            "maximum, so a caller who wants the whole queue can say so."
        ),
        scope=Scope.PRODUCT,
        reload=Reload.RESTART,
        env_var="KAE_CLARIFICATION_LIMIT",
        minimum=1,
        maximum=100,
        implication="Affects how many questions an agent puts to a person per call.",
    ),
)

BY_KEY: Mapping[str, Setting] = {setting.key: setting for setting in CATALOG}


def require(key: str) -> Setting:
    """Return one setting's contract, or say which keys exist.

    Raising rather than returning `None`: every caller of this would have to
    handle the absence, and the only correct handling is to fail.
    """

    setting = BY_KEY.get(key)
    if setting is None:
        raise SettingError(f"unknown setting {key!r}. Known keys: {', '.join(sorted(BY_KEY))}")
    return setting


def coerce(setting: Setting, raw: Any, source: Source) -> Any:
    """Convert and check one value, naming where it came from if it fails.

    The source is in the message on purpose. "KAE_MAX_PAGE_SIZE=lots is not an
    integer" is actionable; "invalid setting" sends someone to read the code.
    """

    try:
        value = _convert(setting.kind, raw)
    except (TypeError, ValueError):
        raise SettingError(
            f"{setting.key} from {source.value} is {raw!r}, which is not "
            f"{setting.kind.__name__} ({setting.unit})"
        ) from None

    if setting.ceiling is not None and value > setting.ceiling:
        raise SettingError(
            f"{setting.key} from {source.value} is {value}, above the coded "
            f"ceiling of {setting.ceiling}. This boundary is not overridable: "
            f"{setting.implication or setting.rationale}"
        )
    if setting.minimum is not None and value < setting.minimum:
        raise SettingError(
            f"{setting.key} from {source.value} is {value}, below the minimum "
            f"of {setting.minimum} ({setting.unit})"
        )
    if setting.maximum is not None and value > setting.maximum:
        raise SettingError(
            f"{setting.key} from {source.value} is {value}, above the maximum "
            f"of {setting.maximum} ({setting.unit})"
        )
    return value


def _convert(kind: type, raw: Any) -> Any:
    """Read a value of the declared type, refusing near-misses.

    `bool` is handled by name rather than by truthiness, because `bool("false")`
    is `True` and a deployment that turned something off would find it on.
    """

    if kind is bool:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
        raise ValueError(text)
    if kind is int:
        # Rejects "20.5" rather than truncating it: a count that was meant to
        # be fractional is a misunderstanding, not a rounding problem.
        return int(str(raw).strip())
    if kind is float:
        return float(str(raw).strip())
    return str(raw).strip()
