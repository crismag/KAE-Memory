"""Migrations apply and roll back cleanly.

The mapped metadata is the source of truth for the tests; these checks make sure
the committed revisions actually produce it, so a mapping change without a
migration is caught here rather than in production.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from kae_memory.persistence.tables import Base

EXPECTED_TABLES = {
    "agent_runs",
    "knowledge_items",
    "knowledge_provenance_links",
    "knowledge_relationships",
    "knowledge_versions",
    "messages",
    "projects",
    "sessions",
}


@pytest.fixture
def alembic_config(tmp_path: Path) -> tuple[Config, str]:
    """Return an Alembic config pointed at a throwaway database."""

    root = Path(__file__).resolve().parents[2]
    url = f"sqlite+pysqlite:///{tmp_path / 'migrations.db'}"
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config, url


def test_upgrade_creates_every_mapped_table(alembic_config: tuple[Config, str]) -> None:
    config, url = alembic_config

    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        present = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert present >= EXPECTED_TABLES
    assert set(Base.metadata.tables) <= present


def test_downgrade_removes_every_table(alembic_config: tuple[Config, str]) -> None:
    config, url = alembic_config

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(url)
    try:
        remaining = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert not (EXPECTED_TABLES & remaining)


def test_revision_0002_is_additive_over_0001(alembic_config: tuple[Config, str]) -> None:
    """Revision 0001 stands alone; 0002 only adds to it."""

    config, url = alembic_config

    command.upgrade(config, "0001")
    engine = create_engine(url)
    try:
        after_first = set(inspect(engine).get_table_names())
        command.upgrade(config, "0002")
        after_second = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {"knowledge_items", "knowledge_versions"} <= after_first
    assert after_first < after_second
