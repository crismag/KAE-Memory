"""Run rule synthesis: extracted `rule v1` rows to a rule model with weights.

`04-RULES-CONTROLS.md`, and `D-132`/`D-133`. The extracted rows stay where they
are and keep their lifecycle. What this adds is a `synthesized_objects` row per
rule, the two things a **person** attributes to it, and one idempotent event.

## The rule itself needs no table

Its family, its authority, whether it is active and whether it is a control are
all derived — from the statement for the family, and from the attribution for
everything that carries weight. A column beside the object would be `D-125`'s
second copy of a state, free to disagree after a rerun.

## Two tables for the two things nothing else holds

`rule_attributions` is where a rule came from: one row per rule, because a rule
has exactly one origin. `rule_enforcement_mechanisms` is what enforces it: many
rows per rule, or none. Sharing one table would repeat the origin on every
mechanism row, which is `D-133`'s reason for two.

## The run writes to neither

Not once. An origin KAE attributed would make the rule active by the act of
synthesising it, and a mechanism KAE named would make it a control the same way
— `D-131`'s refusal in the same shape, twice. So ``synthesize`` reads both and
writes neither, and ``record_attribution`` and ``record_mechanism`` are reached
only by a person's request.

## Acceptance is read from the source, never stored

An attribution may name the synthesized object the rule leans on, and then the
rule is active only while that object is authoritative: deriving a control from
a proposal is `D-126`'s laundering. An attribution naming no source object is a
person's direct assertion of provenance and is active on the strength of it,
because there is no other row to defer to.

## Nothing here becomes attention

The gap this layer can honestly report is a rule nobody attributed, and one
interrupt per unattributed rule is the review queue `ADR-0007` exists to remove
under a new name. Ranking gaps by what they block is `SYN-11`.

## Rerunning changes nothing

Identity is the statement, normalised, for the objects; the rule for an
attribution; and ``(rule, name)`` for a mechanism. Unchanged evidence produces
the same keys and therefore the same rows, and the run's event replays instead
of being recorded again.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.application.goal_synthesis_service import identity_key_for
from kae_memory.application.synthesis_service import SynthesisService
from kae_memory.domain.errors import KnowledgeNotFoundError
from kae_memory.domain.identifiers import (
    KnowledgeItemId,
    ProjectId,
    RuleAttributionId,
    RuleEnforcementMechanismId,
    SynthesizedObjectId,
)
from kae_memory.domain.lifecycle import RETRIEVABLE
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.synthesis import (
    ChangeTrigger,
    EvidenceBindingKind,
    RuleAttributionRecord,
    RuleEnforcementMechanismRecord,
    SynthesizedLifecycle,
)
from kae_memory.domain.synthesizers.rules import (
    RuleAuthority,
    RuleCandidate,
    RuleFamily,
    RuleOrigin,
    plan_rule_model,
)
from kae_memory.persistence.readiness_repositories import bump_knowledge_revision
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.synthesis_repository import SynthesisRepository
from kae_memory.persistence.transactions import run_transaction


@dataclass(frozen=True, slots=True)
class SynthesizedRule:
    """One rule as the run wrote it, with everything that decides its weight."""

    object_id: SynthesizedObjectId
    statement: str
    family: RuleFamily
    origin: RuleOrigin
    authority: RuleAuthority
    active: bool
    enforceable: bool
    mechanisms: tuple[str, ...]
    capability_areas: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleSynthesisReport:
    """What one run concluded, including what it could not weigh."""

    project_id: ProjectId
    replayed: bool
    considered: int
    rules: tuple[SynthesizedRule, ...]

    @property
    def by_family(self) -> dict[RuleFamily, int]:
        """What the run read each rule as being about. Derived, never stored."""

        return dict(Counter(one.family for one in self.rules))

    @property
    def active(self) -> int:
        """How many rules govern anything."""

        return sum(1 for one in self.rules if one.active)

    @property
    def controls(self) -> int:
        """Doc 04's *active controls* — governing and enforced by a named mechanism."""

        return sum(1 for one in self.rules if one.active and one.enforceable)

    @property
    def unattributed(self) -> tuple[str, ...]:
        """The rules nobody said the origin of. Usually all of them, and that is the finding."""

        return tuple(
            one.statement for one in self.rules if one.authority is RuleAuthority.UNATTRIBUTED
        )

    @property
    def families(self) -> tuple[RuleFamily, ...]:
        """The families present among active rules, in doc 04's declared order."""

        present = {one.family for one in self.rules if one.active}
        return tuple(family for family in RuleFamily if family in present)


class RuleSynthesisService:
    """Turn rule evidence into the project's rule model."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory
        self._synthesis = SynthesisService(session_factory)

    def synthesize(
        self, project_id: ProjectId, *, idempotency_key: str | None = None
    ) -> RuleSynthesisReport:
        """Plan and persist the rule model for one project."""

        started = datetime.now(UTC)
        statements, members_of = self._read(project_id)
        attributed, mechanisms = self._attributions_by_statement(project_id)

        candidates = tuple(
            RuleCandidate(
                members=tuple(str(member) for member in members_of[key]),
                canonical_key=key,
                statement=statement,
                origin=attributed.get(key, (RuleOrigin.UNATTRIBUTED, False))[0],
                source_accepted=attributed.get(key, (RuleOrigin.UNATTRIBUTED, False))[1],
                enforcement_mechanisms=tuple(mechanisms.get(key, ())),
            )
            for key, statement in sorted(statements.items())
        )
        plan = plan_rule_model(candidates)

        summary = (
            f"rules: {len(plan.rules)} rules, {len(plan.active)} active, "
            f"{len(plan.controls)} controls, {len(plan.unattributed)} unattributed"
        )
        key = (idempotency_key or f"rule-synthesis:{len(candidates)}:{len(plan.active)}").strip()

        rules: list[SynthesizedRule] = []
        for planned in plan.rules:
            statement = planned.candidate.statement
            obj = self._synthesis.put_object(
                project_id,
                domain=KnowledgeKind.RULE.value,
                identity_key=identity_key_for(statement),
                title=statement,
                statement=statement,
            )
            rules.append(
                SynthesizedRule(
                    object_id=obj.id,
                    statement=statement,
                    family=planned.family,
                    origin=planned.candidate.origin,
                    authority=planned.authority,
                    active=planned.active,
                    enforceable=planned.enforceable,
                    mechanisms=planned.candidate.enforcement_mechanisms,
                    capability_areas=planned.capability_areas,
                )
            )
            for member in members_of[planned.candidate.canonical_key]:
                self._synthesis.bind_evidence(
                    project_id, obj.id, member, EvidenceBindingKind.SUPPORTS
                )

        event = self._synthesis.record_change(
            project_id,
            idempotency_key=key,
            trigger=ChangeTrigger.RECONCILIATION,
            summary=summary,
        )

        return RuleSynthesisReport(
            project_id=project_id,
            replayed=event.created_at is not None and event.created_at < started,
            considered=len(candidates),
            rules=tuple(rules),
        )

    def record_attribution(
        self,
        project_id: ProjectId,
        rule_object_id: SynthesizedObjectId,
        origin: RuleOrigin,
        source_object_id: SynthesizedObjectId | None = None,
    ) -> RuleAttributionRecord:
        """Record where one rule came from.

        **Only a person reaches this.** No synthesis path calls it, because an
        origin KAE attributed would make the rule active by the act of
        synthesising it (`D-132`).

        Idempotent by rule: re-attributing replaces the origin rather than
        stacking a second, since a rule has exactly one place it came from.
        """

        def operation(session: DbSession) -> RuleAttributionRecord:
            repo = SynthesisRepository(session)
            self._require_rule(repo, project_id, rule_object_id)
            if source_object_id is not None:
                source = repo.get_object(source_object_id)
                if source is None or source.project_id != project_id:
                    raise KnowledgeNotFoundError(f"unknown synthesized object: {source_object_id}")
            now = datetime.now(UTC)
            existing = repo.get_attribution(rule_object_id)
            record = RuleAttributionRecord(
                id=existing.id if existing is not None else RuleAttributionId(str(uuid4())),
                project_id=project_id,
                rule_object_id=rule_object_id,
                origin=origin.value,
                source_object_id=source_object_id,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
            )
            repo.save_attribution(record)
            bump_knowledge_revision(session, project_id)
            return record

        return run_transaction(self._session_factory, operation)

    def record_mechanism(
        self, project_id: ProjectId, rule_object_id: SynthesizedObjectId, name: str
    ) -> RuleEnforcementMechanismRecord:
        """Record what enforces one rule — a check, a permission, a gate.

        **Only a person reaches this**, for `D-132`'s reason: a mechanism KAE
        named would make every rule an enforceable control by the act of
        synthesising it.

        Idempotent by ``(rule, normalised name)``, so re-naming the same
        mechanism updates its wording rather than stacking a second row.
        """

        name = name.strip()
        identity = identity_key_for(name)

        def operation(session: DbSession) -> RuleEnforcementMechanismRecord:
            repo = SynthesisRepository(session)
            self._require_rule(repo, project_id, rule_object_id)
            now = datetime.now(UTC)
            existing = repo.get_mechanism(rule_object_id, identity)
            record = RuleEnforcementMechanismRecord(
                id=(
                    existing.id
                    if existing is not None
                    else RuleEnforcementMechanismId(str(uuid4()))
                ),
                project_id=project_id,
                rule_object_id=rule_object_id,
                identity_key=identity,
                name=name,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
            )
            repo.save_mechanism(record)
            bump_knowledge_revision(session, project_id)
            return record

        return run_transaction(self._session_factory, operation)

    def list_attributions(
        self, project_id: ProjectId, rule_object_id: SynthesizedObjectId | None = None
    ) -> tuple[RuleAttributionRecord, ...]:
        """The project's rule attributions, optionally for one rule.

        Empty is the ordinary answer and doc 04's opening complaint: rules
        recorded without where they came from are interchangeable rows.
        """

        def operation(session: DbSession) -> tuple[RuleAttributionRecord, ...]:
            return SynthesisRepository(session).list_attributions(project_id, rule_object_id)

        return run_transaction(self._session_factory, operation)

    def list_mechanisms(
        self, project_id: ProjectId, rule_object_id: SynthesizedObjectId | None = None
    ) -> tuple[RuleEnforcementMechanismRecord, ...]:
        """The mechanisms named in this project, optionally for one rule.

        Empty means the project has no enforceable controls, which is a finding
        about the project rather than about the rules.
        """

        def operation(session: DbSession) -> tuple[RuleEnforcementMechanismRecord, ...]:
            return SynthesisRepository(session).list_mechanisms(project_id, rule_object_id)

        return run_transaction(self._session_factory, operation)

    @staticmethod
    def _require_rule(
        repo: SynthesisRepository, project_id: ProjectId, rule_object_id: SynthesizedObjectId
    ) -> None:
        """Refuse to attribute anything to an object that is not this project's rule."""

        rule = repo.get_object(rule_object_id)
        if rule is None or rule.project_id != project_id:
            raise KnowledgeNotFoundError(f"unknown synthesized object: {rule_object_id}")
        if rule.domain != KnowledgeKind.RULE.value:
            raise KnowledgeNotFoundError(f"not a rule: {rule_object_id} is a {rule.domain}")

    def _attributions_by_statement(
        self, project_id: ProjectId
    ) -> tuple[dict[str, tuple[RuleOrigin, bool]], dict[str, list[str]]]:
        """Stored attributions and mechanisms, keyed by the rule's identity key.

        The join is by identity key — the normalised statement `put_object`
        stored the rule under — so no second mapping exists to drift.

        Acceptance is resolved here rather than stored: a named source counts
        only while it is authoritative, and an attribution naming no source is a
        person's direct assertion and counts on its own (`D-133`).
        """

        def operation(
            session: DbSession,
        ) -> tuple[dict[str, tuple[RuleOrigin, bool]], dict[str, list[str]]]:
            repo = SynthesisRepository(session)
            objects = {obj.id: obj for obj in repo.list_objects(project_id)}
            attributed: dict[str, tuple[RuleOrigin, bool]] = {}
            for record in repo.list_attributions(project_id):
                rule = objects.get(record.rule_object_id)
                if rule is None:
                    continue
                source = (
                    None
                    if record.source_object_id is None
                    else objects.get(record.source_object_id)
                )
                accepted = record.source_object_id is None or (
                    source is not None and source.lifecycle is SynthesizedLifecycle.AUTHORITATIVE
                )
                attributed[rule.identity_key] = (RuleOrigin(record.origin), accepted)

            mechanisms: dict[str, list[str]] = {}
            for mechanism in repo.list_mechanisms(project_id):
                rule = objects.get(mechanism.rule_object_id)
                if rule is None:
                    continue
                mechanisms.setdefault(rule.identity_key, []).append(mechanism.name)
            return attributed, mechanisms

        return run_transaction(self._session_factory, operation)

    def _read(
        self, project_id: ProjectId
    ) -> tuple[dict[str, str], dict[str, tuple[KnowledgeItemId, ...]]]:
        """Read rule evidence, grouping identical wordings.

        Confirmation of the evidence is deliberately not read here. Doc 04's
        weight comes from the origin, and a person confirming that a sentence
        was said is not a person saying where the rule came from (`D-132`).
        """

        def operation(
            session: DbSession,
        ) -> tuple[dict[str, str], dict[str, tuple[KnowledgeItemId, ...]]]:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            items = knowledge.list_for_project(project_id, None)

            grouped: dict[str, list[KnowledgeItemId]] = {}
            statement_of: dict[str, str] = {}
            for item in items:
                if item.lifecycle not in RETRIEVABLE:
                    continue
                if item.kind != KnowledgeKind.RULE.value:
                    continue
                content = item.current_version.content
                key = identity_key_for(content)
                if not key:
                    continue
                grouped.setdefault(key, []).append(item.id)
                statement_of.setdefault(key, content)

            members_of = {key: tuple(members) for key, members in grouped.items()}
            return statement_of, members_of

        return run_transaction(self._session_factory, operation)
