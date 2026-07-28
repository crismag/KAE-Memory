"""``python -m kae_memory.api``.

The portable entrypoint ADR-0013 requires: the same command runs the API
locally, under Docker Compose, under systemd, or on a managed container runtime.
Configuration arrives through the environment; nothing here is platform-specific.
"""

import uvicorn

from .app import app_from_environment
from .dependencies import Settings


def main() -> None:
    """Serve the API."""

    settings = Settings.from_environment()
    uvicorn.run(app_from_environment(), host=settings.host, port=settings.port)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
