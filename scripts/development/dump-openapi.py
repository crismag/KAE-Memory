"""Write the recorded OpenAPI document (N9).

Run against the application factory rather than a live server: schema generation
touches no database, so the document can be regenerated anywhere.

It lived under `frontend/` and was the input to a generated TypeScript client.
That client is gone; the **document is not**, because the check that regenerates
it and diffs it is the only automated notice that the HTTP surface changed
shape. That was always a backend guard living in a frontend directory.

`tests/api/test_recorded_contract.py` is the guard now, so a contract change
fails in the command a developer already runs rather than fifteen minutes later
in a job that needs a Node toolchain.
"""

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.api import create_app


def main() -> None:
    """Write `specifications/openapi.json`, or the path given as the first argument."""

    # A lazily-connected engine: create_app stores the factory and never opens a
    # connection until a request arrives, and none does here.
    factory = sessionmaker(create_engine("cockroachdb+psycopg://root@localhost:26257/unused"))
    document = create_app(factory).openapi()

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "specifications/openapi.json")
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"wrote {target} ({len(document['paths'])} paths)")


if __name__ == "__main__":
    main()
