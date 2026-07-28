"""The HTTP interface.

A transport over the application layer, never a second place where business
rules live (ADR-0004, ADR-0014). Importing this package requires the ``api``
extra: ``pip install 'kae-memory[api]'``.
"""

from .app import app_from_environment, create_app

__all__ = ["app_from_environment", "create_app"]
