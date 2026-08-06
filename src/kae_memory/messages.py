"""Backend messages that more than one adapter has to say the same way (N8).

**Not a mechanical centralisation of every string**, which the focus file rules
out and which would trade one problem for a worse one: a file of four hundred
keys nobody reads, and a message you cannot understand without opening a second
file to find its text.

What is here is the narrow set that earns a stable key — sentences said by both
adapters, where drift is not cosmetic:

*Integrity notes.* "Reported, not verified" and "classification is not truth"
are epistemic caveats. One adapter dropping or softening one would produce a
response that overstates what KAE knows, which is the failure this whole system
is built against. These were already duplicated three ways, and two of the
copies had quietly diverged in their second sentence.

*Cross-adapter refusals.* An unknown purpose is refused by both HTTP and MCP,
and a caller who reads two different explanations for one rejection learns that
the two surfaces are different products.

*Environment failures.* The missing-extra message appeared in three adapters
and is the same instruction each time.

What is deliberately **not** here: docstrings, one-off errors, test fixtures,
domain invariant messages that name their own field, and anything said in
exactly one place. A message with one caller is not duplicated; moving it here
would cost a lookup and buy nothing.

Frontend copy belongs to KAE-Studio and never appears in this file.
"""

from __future__ import annotations

from typing import Any

MESSAGES: dict[str, str] = {
    # -- integrity notes ---------------------------------------------------
    # Said by both adapters, and the reason they must not drift: each is a
    # caveat about what a response does *not* establish. A softened copy is a
    # response claiming more than KAE knows.
    "integrity.operational_reported": (
        "Reported, not verified. A milestone is never completed because a "
        "sentence said so; a proposed record is a claim nobody has accepted."
    ),
    "integrity.classification_not_truth": (
        "Classification says what a span was, not whether it is true. "
        "Nothing listed here is confirmed knowledge."
    ),
    # Two keys, not one. The read form above says nothing was confirmed; this
    # one adds that nothing *moved*, because a submission can create
    # operational records and a read cannot. Collapsing them would make a list
    # response deny having changed a status it was never in a position to
    # change — a caveat about an action nobody took reads as reassurance about
    # the wrong thing.
    "integrity.classification_no_status_change": (
        "Classification says what a span was, not whether it is true. "
        "Nothing here is confirmed knowledge, and no operational status "
        "changed: a reported transition is a proposal."
    ),
    "integrity.nothing_confirmed": (
        "Nothing here is confirmed by being returned. A person confirms what "
        "becomes project knowledge."
    ),
    # -- cross-adapter refusals -------------------------------------------
    "refusal.unknown_purpose": ("unknown purpose {purpose!r}; expected one of {valid}"),
    # "no X service" rather than "a/an X service": one template, and no caller
    # has to supply an article to keep the sentence grammatical.
    "refusal.capability_unconfigured": "no {capability} service is configured for this server",
    # -- environment -------------------------------------------------------
    "environment.bedrock_extra_missing": (
        "the bedrock extra is not installed: uv sync --extra bedrock"
    ),
    "environment.region_unresolved": (
        "{variable} requires an AWS region via AWS_REGION, AWS_DEFAULT_REGION, "
        "or the active AWS profile."
    ),
}
"""Stable key to template. Keys are dotted and namespaced by what they are for.

Stability is the contract: a key appears in tests and, for the refusals, in
whatever a caller matches on. Renaming one is a breaking change even though
nothing type-checks it.
"""


class UnknownMessageError(KeyError):
    """No message is registered under that key."""


def message(key: str, **values: Any) -> str:
    """Render one message, refusing a key or a placeholder that does not exist.

    Both failures are raised rather than papered over. A `KeyError` at the call
    site is a bug found in a test; a message rendered with a literal
    `{purpose}` in it is a bug found by whoever reads the response.
    """

    template = MESSAGES.get(key)
    if template is None:
        raise UnknownMessageError(
            f"unknown message {key!r}. Known keys: {', '.join(sorted(MESSAGES))}"
        )
    try:
        return template.format(**values)
    except (KeyError, IndexError) as error:
        raise UnknownMessageError(
            f"message {key!r} needs a value this call did not supply: {error}"
        ) from None


def placeholders(key: str) -> frozenset[str]:
    """Return the names a message expects, for a test that checks callers.

    Derived from the template rather than declared beside it, so the two cannot
    disagree.
    """

    import string

    template = MESSAGES.get(key)
    if template is None:
        raise UnknownMessageError(f"unknown message {key!r}")
    return frozenset(
        name.split("!")[0].split(":")[0]
        for _, name, _, _ in string.Formatter().parse(template)
        if name
    )
