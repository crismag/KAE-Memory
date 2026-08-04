"""Copy a KAE-Memory dataset from one provider to another.

Provider switching moves no data by design (ADR-0022): a deployment that changes
provider reads whatever is in the newly selected store, which is usually
nothing. This is the separate, deliberate step that carries a dataset across.

One-time and one-directional. It is not replication, not synchronisation, and
not a failover path — running it does not keep two stores in step, and nothing
here should grow into something that pretends to.

The target schema must already exist at the revision the data expects. This
copies rows; ``alembic upgrade head`` creates the shape they go into.

Usage::

    python scripts/development/copy-database.py \\
        --source cockroachdb+psycopg://root@localhost:26259/kae_dev?sslmode=disable \\
        --target postgresql+psycopg://kae:kae@127.0.0.1:5432/kae_memory \\
        [--dry-run] [--replace]

Refuses a non-empty target unless ``--replace`` is given: silently merging two
datasets would produce a store whose provenance nobody can reconstruct.
"""

import argparse
import json
import sys

from sqlalchemy import Table, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

sys.path.insert(0, "src")

from kae_memory.persistence.tables import Base, Vector

BATCH = 200


def _is_vector(column) -> bool:
    return isinstance(column.type, Vector)


def _is_json(column) -> bool:
    return isinstance(column.type, JSONB)


def _placeholder(column) -> str:
    """Return the bind expression for one column.

    Both special cases are about text crossing a type boundary: a vector arrives
    from the source as its ``'[1,2,3]'`` literal and a JSONB value as a Python
    object, and each needs an explicit cast rather than whatever the driver
    guesses.
    """

    if _is_vector(column):
        return f"CAST(:{column.name} AS vector({column.type.dimensions}))"
    if _is_json(column):
        return f"CAST(:{column.name} AS jsonb)"
    return f":{column.name}"


def _adapt(column, value):
    if value is None:
        return None
    if _is_json(column) and not isinstance(value, str):
        return json.dumps(value)
    return value


def _table_exists(engine: Engine, name: str) -> bool:
    with engine.connect() as connection:
        try:
            connection.execute(text(f"SELECT 1 FROM {name} LIMIT 1"))
            return True
        except Exception:
            return False


def _count(engine: Engine, name: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {name}")).scalar() or 0)


def _copy_table(source: Engine, target: Engine, table: Table, dry_run: bool) -> int:
    columns = list(table.columns)
    names = ", ".join(column.name for column in columns)
    values = ", ".join(_placeholder(column) for column in columns)
    insert = f"INSERT INTO {table.name} ({names}) VALUES ({values})"

    with source.connect() as reader:
        rows = reader.execute(text(f"SELECT {names} FROM {table.name}")).mappings().all()
    if not rows or dry_run:
        return len(rows)

    with target.begin() as writer:
        for start in range(0, len(rows), BATCH):
            batch = [
                {column.name: _adapt(column, row[column.name]) for column in columns}
                for row in rows[start : start + BATCH]
            ]
            writer.execute(text(insert), batch)
    return len(rows)


def main() -> int:
    """Copy every mapped table, in dependency order."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Empty the target's mapped tables first. Destructive.",
    )
    args = parser.parse_args()

    source = create_engine(args.source, isolation_level="AUTOCOMMIT")
    target = create_engine(args.target)

    # Dependency order, so a foreign key never points at a row that has not
    # arrived yet. Reversed for deletion, for the same reason.
    ordered = list(Base.metadata.sorted_tables)

    occupied = [t.name for t in ordered if _table_exists(target, t.name) and _count(target, t.name)]
    if occupied and not args.replace:
        print(
            "target already holds data in: " + ", ".join(occupied),
            "\nRefusing to merge two datasets. Pass --replace to empty them first.",
            file=sys.stderr,
        )
        return 2

    if occupied and args.replace and not args.dry_run:
        with target.begin() as connection:
            for table in reversed(ordered):
                if _table_exists(target, table.name):
                    connection.execute(text(f"DELETE FROM {table.name}"))
        print(f"emptied {len(occupied)} table(s) in the target")

    copied = 0
    skipped: list[str] = []
    for table in ordered:
        if not _table_exists(source, table.name):
            # The source predates a migration the target has. Nothing to carry.
            skipped.append(table.name)
            continue
        moved = _copy_table(source, target, table, args.dry_run)
        copied += moved
        print(f"  {table.name:32} {moved}")

    print(f"\n{'would copy' if args.dry_run else 'copied'} {copied} row(s)")
    if skipped:
        print(f"absent in source, nothing to copy: {', '.join(skipped)}")

    if not args.dry_run:
        print("\nverifying:")
        mismatched = 0
        for table in ordered:
            if table.name in skipped:
                continue
            expected = _count(source, table.name)
            actual = _count(target, table.name)
            if expected != actual:
                mismatched += 1
                print(f"  MISMATCH {table.name}: source {expected}, target {actual}")
        if mismatched:
            print(f"{mismatched} table(s) do not match", file=sys.stderr)
            return 1
        print("  every table matches the source")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
