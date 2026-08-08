"""Removing a project, and everything that hangs off it (T0.2, F-021).

Nine tables reference `projects` and **every foreign key is `NO ACTION`**, so
`DELETE FROM projects` fails on a violation. There is no cascade to rely on and
no delete on any adapter, so removing a project has meant hand-ordered SQL
against production — the direct-write path ADR-0027 and F-011 exist to
discourage.

## Why this is a service and not a script

The child ordering is domain knowledge. A script that gets it wrong does not
fail cleanly; it half-deletes a project and leaves rows pointing at something
that no longer exists. Putting it here means the ordering is derived, tested,
and reviewed with everything else.

## The ordering is derived, not written down

`sort_tables` gives a dependency order for creation; deletion is its reverse.
Hand-maintaining a list of twenty-three tables guarantees that the next table
someone adds is the one nobody remembers, and the failure would be silent for
exactly the rows that matter least until they matter.

## Identifiers are supplied, never matched

`plan` and `delete` take explicit ids. **This service never selects by name,
pattern, or age.** Choosing what to delete is a judgement someone makes by
reading a list; performing it is what this does. A pattern accepted here would
be a pattern eventually run against a name somebody real had chosen.

Protection is enforced anyway, as a second line: a caller passing a protected id
is refused rather than trusted to have filtered first.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import sort_tables

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.tables import Base, KnowledgeItemRow, KnowledgeVersionRow, ProjectRow
from kae_memory.persistence.transactions import run_transaction


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    """One project a deletion would touch, as a person needs to read it."""

    project_id: str
    name: str
    knowledge_revision: int


@dataclass(frozen=True, slots=True)
class DeletionPlan:
    """What a deletion would remove, before anything is removed.

    `rows` counts per table so a reviewer can sanity-check scale rather than
    trust a total. A project reporting zero messages when the reviewer expected
    hundreds is the signal that the wrong ids were pasted in.
    """

    projects: tuple[ProjectSummary, ...]
    rows: dict[str, int] = field(default_factory=dict)
    missing: tuple[str, ...] = ()

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())


class ProjectDeletionError(DomainInvariantError):
    """A deletion this service refuses to perform."""


def _project_scoped_tables() -> list[str]:
    """Every table carrying a `project_id`, in a safe order to delete from.

    Reverse dependency order: children before parents. Derived from the mapped
    metadata so a table added later is covered without anyone remembering.
    """

    ordered = sort_tables(Base.metadata.sorted_tables)
    return [t.name for t in reversed(ordered) if "project_id" in t.c and t.name != "projects"]


class ProjectDeletionService:
    """Delete projects and everything scoped to them."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory

    def plan(self, project_ids: Sequence[ProjectId | str]) -> DeletionPlan:
        """Report what deleting these projects would remove. Changes nothing."""

        wanted = [str(p) for p in project_ids]

        def operation(session: DbSession) -> DeletionPlan:
            rows = session.execute(
                select(ProjectRow).where(ProjectRow.project_id.in_(wanted))
            ).scalars()
            found = tuple(
                ProjectSummary(
                    project_id=r.project_id, name=r.name, knowledge_revision=r.knowledge_revision
                )
                for r in rows
            )
            present = {p.project_id for p in found}

            counts: dict[str, int] = {}
            for table_name in _project_scoped_tables():
                table = Base.metadata.tables[table_name]
                # `cast` on neither side: `project_id` is `String(64)` on some
                # tables and a UUID string on others, and comparing against the
                # same Python strings works for both.
                count = session.execute(
                    select(func.count()).select_from(table).where(table.c.project_id.in_(wanted))
                ).scalar_one()
                if count:
                    counts[table_name] = int(count)

            versions = session.execute(
                select(func.count())
                .select_from(KnowledgeVersionRow)
                .where(
                    KnowledgeVersionRow.knowledge_item_id.in_(
                        select(KnowledgeItemRow.id).where(KnowledgeItemRow.project_id.in_(wanted))
                    )
                )
            ).scalar_one()
            if versions:
                counts["knowledge_versions"] = int(versions)

            return DeletionPlan(
                projects=found,
                rows=counts,
                # Reported rather than raised. A caller planning a deletion from
                # a stale list needs to see which ids no longer exist, and an
                # exception would tell them only that one of them did not.
                missing=tuple(sorted(set(wanted) - present)),
            )

        return run_transaction(self._session_factory, operation)

    def delete(
        self,
        project_ids: Sequence[ProjectId | str],
        *,
        protected: Iterable[ProjectId | str] = (),
    ) -> DeletionPlan:
        """Delete these projects and everything scoped to them, in one transaction.

        Returns the plan that was executed, so the caller can record what was
        removed rather than what was requested — they differ whenever an id in
        the request no longer existed.

        Refuses an empty request. A deletion with nothing to delete is almost
        always a filter that matched nothing, and returning success teaches the
        caller their filter worked.
        """

        wanted = [str(p) for p in project_ids]
        if not wanted:
            raise ProjectDeletionError(
                "no projects named. An empty deletion is a filter that matched nothing, "
                "and reporting success for it is how the next one is trusted."
            )

        forbidden = sorted(set(wanted) & {str(p) for p in protected})
        if forbidden:
            raise ProjectDeletionError(
                f"refusing to delete protected projects: {forbidden}. Protection is "
                f"checked here as well as by the caller, because a filter that has "
                f"already gone wrong is not a filter worth trusting twice."
            )

        plan = self.plan(wanted)

        def operation(session: DbSession) -> DeletionPlan:
            # Versions first: they hang off knowledge items rather than off the
            # project, so nothing else deletes them.
            session.execute(
                delete(KnowledgeVersionRow).where(
                    KnowledgeVersionRow.knowledge_item_id.in_(
                        select(KnowledgeItemRow.id).where(KnowledgeItemRow.project_id.in_(wanted))
                    )
                )
            )
            for table_name in _project_scoped_tables():
                table = Base.metadata.tables[table_name]
                session.execute(delete(table).where(table.c.project_id.in_(wanted)))
            session.execute(delete(ProjectRow).where(ProjectRow.project_id.in_(wanted)))
            return plan

        return run_transaction(self._session_factory, operation)


__all__ = [
    "DeletionPlan",
    "ProjectDeletionError",
    "ProjectDeletionService",
    "ProjectSummary",
]
