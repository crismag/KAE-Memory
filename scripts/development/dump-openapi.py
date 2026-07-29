"""Write the OpenAPI document the generated client is built from.

Run against the application factory rather than a live server: schema generation
touches no database, so the document can be regenerated in CI without a cluster.
"""

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.api import create_app


def main() -> None:
    """Write `frontend/openapi.json`, or the path given as the first argument."""

    # A lazily-connected engine: create_app stores the factory and never opens a
    # connection until a request arrives, and none does here.
    factory = sessionmaker(create_engine("cockroachdb+psycopg://root@localhost:26257/unused"))
    document = create_app(factory).openapi()

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/openapi.json")
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"wrote {target} ({len(document['paths'])} paths)")


if __name__ == "__main__":
    main()
