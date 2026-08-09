"""Every field a domain object carries reaches the response that returns it.

**This exists because "declared" is not "reached".**
`test_no_unreachable_capability.py` walks the services and asks whether each is
declared on an adapter. That catches a capability nothing can call. It cannot
catch the failure that actually kept happening, which is subtler and was found
three times in one day:

* `IngestionService.enqueue_review` was on a route, and no caller ever called
  it — so readiness reported 0% on every project for as long as it existed.
* `AssumptionService.record` took an `origin`, and the request schema did not
  offer one — so `kae_recommended_accepted` could not be written over HTTP at
  all, which is precisely the origin the product needs to keep KAE's advice
  distinguishable from what a person said.
* `Message.metadata` was modelled, persisted, and returned by nothing — so a
  caller could write structure about a turn and never read it back, and kept
  its own copy instead.

Each was healthy from below and healthy from above. What was missing was the
join, and no test looked at joins.

## What this checks, and what it deliberately does not

**Response models that wrap one domain object.** Where a `Response.of(x)` takes
a single dataclass, every field of that dataclass must appear on the response —
or be exempted here, with the reason.

It does **not** check request schemas, because a request legitimately accepts
less than a domain object holds: identity and timestamps are the server's to
assign. `origin` slipped through for that reason, and the honest fix for that
class is a review habit rather than a test that would cry wolf on every
`created_at`.

It does **not** check aggregate responses — `of(items, limit)` — because their
shape is a summary by design.

## Exemptions carry reasons

Same rule the capability registry applies: an exception without a reason is
indistinguishable from an oversight, and the cost of writing one down is what
keeps them rare.
"""

from __future__ import annotations

import inspect
from dataclasses import fields, is_dataclass
from typing import get_type_hints

import pytest
from pydantic import BaseModel

from kae_memory.api import schemas

#: Fields a response may omit, and why.
#:
#: Keyed `Response.field`. Each entry is a decision; an absent key is a defect.
EXEMPT: dict[str, str] = {
    "MessageResponse.actor_id": (
        "Attribution is recorded and deliberately not returned to a browser. "
        "Who said something is Memory's audit trail, not the transcript's."
    ),
    "MessageResponse.agent_run_id": (
        "Internal linkage. A client that needed it would be reaching into "
        "execution, which is what the run resources are for."
    ),
    "MessageResponse.idempotency_key": (
        "The caller supplied it. Returning it would invite treating it as an "
        "identifier, which it is not — the message id is."
    ),
    "MessageResponse.purpose": (
        "EM-2 input, not output. It gates interpretation on the way in; a "
        "reader of the transcript is looking at what was said."
    ),
    "MessageResponse.project_id": (
        "The session names the project, and the route is already scoped to it."
    ),
    "RunResponse.lease": (
        "Which worker holds the run and until when. Scheduler internals: a "
        "client that reasoned about a lease would be racing the worker for it."
    ),
    "RunResponse.next_attempt_at": (
        "When the backoff expires. Same reason as the lease — a caller acting "
        "on it would be scheduling, which is the worker's job."
    ),
    "RunResponse.input_context": (
        "What the run was given, which for extraction is the source text "
        "itself. Returning it would duplicate the message on every poll of a "
        "run that already names it."
    ),
}


def _domain_type(model: type[BaseModel]) -> type | None:
    """The single domain dataclass a response wraps, if it wraps exactly one."""

    of = getattr(model, "of", None)
    if of is None:
        return None
    try:
        hints = get_type_hints(of.__func__ if hasattr(of, "__func__") else of)
    except Exception:  # pragma: no cover - a forward ref we cannot resolve
        return None

    signature = inspect.signature(of)
    parameters = [p for name, p in signature.parameters.items() if name != "cls"]
    if len(parameters) != 1:
        # Aggregates and anything needing extra context. Their shape is a
        # summary by design, so field-for-field would be the wrong question.
        return None

    annotated = hints.get(parameters[0].name)
    return annotated if is_dataclass(annotated) else None


def _wrapping_models() -> list[tuple[type[BaseModel], type]]:
    found = []
    for name in dir(schemas):
        model = getattr(schemas, name)
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            continue
        domain = _domain_type(model)
        if domain is not None:
            found.append((model, domain))
    return found


def test_the_check_has_something_to_check() -> None:
    """A guard on the guard.

    If `of` were renamed or the annotations dropped, this file would pass while
    checking nothing — the quietest way for a test to stop working.
    """

    assert len(_wrapping_models()) >= 8


@pytest.mark.parametrize(
    ("model", "domain"),
    _wrapping_models(),
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_every_domain_field_reaches_the_response(model: type[BaseModel], domain: type) -> None:
    exposed = set(model.model_fields)
    missing = sorted(
        f.name
        for f in fields(domain)
        if f.name not in exposed and f"{model.__name__}.{f.name}" not in EXEMPT
    )

    assert not missing, (
        f"{model.__name__} does not return {missing} from {domain.__name__}. "
        f"Either return it, or add it to EXEMPT with the reason — a field that "
        f"is modelled, stored, and returned by nothing is the failure this test "
        f"exists for."
    )


def test_no_exemption_outlives_the_field_it_excuses() -> None:
    """An exemption for a field that no longer exists is stale reasoning.

    It reads as a considered decision and is a leftover, which is worse than no
    entry at all.
    """

    known = {
        f"{model.__name__}.{f.name}"
        for model, domain in _wrapping_models()
        for f in fields(domain)
    }
    stale = sorted(key for key in EXEMPT if key not in known)

    assert not stale, f"these exemptions no longer describe anything: {stale}"


def test_every_exemption_says_why() -> None:
    for key, reason in EXEMPT.items():
        assert len(reason) > 40, f"{key} is exempt without a reason worth reading"
