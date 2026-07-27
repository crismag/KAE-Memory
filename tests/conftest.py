"""Shared test fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.persistence.tables import Base


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    """Return a session factory backed by a file database.

    A file rather than an in-memory database: durability proofs must not depend on
    a single connection staying open.
    """

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'kae.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()
