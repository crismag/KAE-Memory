"""One error envelope, mapped from domain error *types*.

Every failure reaches the client in the same shape, with a stable machine-readable
code (ADR-0014):

```json
{"error": {"code": "domain_invariant_violated", "message": "...", "detail": {}}}
```

The mapping is by exception type, never by matching message text. The domain
already distinguishes an invalid value from an illegal transition; re-deriving
that distinction from strings here would duplicate the meaning in a form that
silently rots.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kae_memory.domain.errors import (
    DomainInvariantError,
    InvalidIdentifierError,
    InvalidLifecycleTransitionError,
    InvalidRunTransitionError,
    StaleVersionError,
)

_LOGGER = logging.getLogger("kae_memory.api")


class ApiError(Exception):
    """A failure the API raises itself, carrying its own status and code."""

    def __init__(
        self, status_code: int, code: str, message: str, detail: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail or {}


def not_found(resource: str, identifier: object) -> ApiError:
    """Return a 404 for a resource that does not exist."""

    return ApiError(404, f"{resource}_not_found", f"No {resource.replace('_', ' ')} {identifier}.")


def error_response(
    status_code: int, code: str, message: str, detail: dict[str, Any] | None = None
) -> JSONResponse:
    """Return the standard error envelope."""

    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


# Conflicts a client could resolve by re-reading state get 409; invalid input
# gets 422. LookupError is what the application layer raises for a missing
# aggregate, so it is the generic 404 rather than an internal failure.
_STATUS_BY_TYPE: tuple[tuple[type[Exception], int, str], ...] = (
    # Ordered most specific first. A stale version is a conflict, not an
    # invariant violation: the caller's decision was valid when they made it,
    # and the wording moved underneath them. 422 would tell them to fix their
    # request; 409 tells them to re-read and decide again, which is what they
    # actually have to do.
    (StaleVersionError, 409, "version_conflict"),
    (InvalidLifecycleTransitionError, 409, "invalid_lifecycle_transition"),
    (InvalidRunTransitionError, 409, "invalid_run_transition"),
    (InvalidIdentifierError, 422, "invalid_identifier"),
    (DomainInvariantError, 422, "domain_invariant_violated"),
    (LookupError, 404, "resource_not_found"),
)


def classify(error: Exception) -> tuple[int, str]:
    """Return the status and code for a domain exception."""

    for kind, status_code, code in _STATUS_BY_TYPE:
        if isinstance(error, kind):
            return status_code, code
    return 500, "internal_error"


def install_error_handlers(app: FastAPI) -> None:
    """Register the handlers that produce the envelope."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, error: ApiError) -> JSONResponse:
        return error_response(error.status_code, error.code, error.message, error.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, error: RequestValidationError) -> JSONResponse:
        return error_response(
            422,
            "validation_failed",
            "The request body or parameters are not valid.",
            {"errors": _serialisable(error.errors())},
        )

    for kind, _status, _code in _STATUS_BY_TYPE:
        app.add_exception_handler(kind, _domain_error)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, error: Exception) -> JSONResponse:
        """Keep the envelope even when nothing anticipated the failure.

        The message is deliberately generic. An unhandled database error carries
        the failing SQL and sometimes the connection string, and neither belongs
        in a client response — the log is where the detail goes.
        """

        _LOGGER.exception("Unhandled error serving request", exc_info=error)
        return error_response(500, "internal_error", "The request could not be completed.")


async def _domain_error(_: Request, error: Exception) -> JSONResponse:
    status_code, code = classify(error)
    return error_response(status_code, code, str(error))


def _serialisable(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Drop the original exception objects pydantic attaches to each error.

    They are not JSON-serialisable, and echoing them would leak internals into a
    client response for no benefit.
    """

    return [
        {key: value for key, value in entry.items() if key != "ctx"}
        for entry in (dict(item) for item in errors)
    ]


ErrorHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]
