"""The step executor that turns a claimed run into agent work.

The agents in :mod:`kae_memory.agents.roles` start their own runs, because M6
drove them directly. A worker claims a run that already exists, so this executor
performs the same work *against an existing run* instead: read the source the run
names, extract, write knowledge, and let the worker complete it.

That split is deliberate rather than duplication for its own sake. Ownership of
the run lifecycle belongs to whoever created it — the agent when invoked
directly, the worker when the API enqueued it — and having both try to succeed
the same run is how a run reaches an illegal transition.
"""

import os
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory import runtime_profile
from kae_memory.agents.deterministic import DeterministicExtractionAdapter
from kae_memory.agents.extraction import ExtractionError, ExtractionPort, ExtractionRequest
from kae_memory.agents.provider import ProviderConfigurationError, resolve_region
from kae_memory.agents.review import (
    ReviewedStatement,
    ReviewFindingKind,
    ReviewPort,
    ReviewRequest,
    judges,
)
from kae_memory.agents.review_adapter import DeterministicReviewAdapter
from kae_memory.application.ingestion_service import DEFAULT_MAX_ITEMS_PER_CHUNK
from kae_memory.application.memory_service import MemoryService, WriteKnowledgeRequest
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import (
    ReviewService,
    Severity,
    classify_offline_by_content,
)
from kae_memory.domain.area_classification import Placement
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole, AgentRun
from kae_memory.domain.identifiers import KnowledgeItemId, MessageId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem
from kae_memory.domain.readiness import SOFTWARE_TEMPLATE

from .runner import FollowUp, StepResult


def _confidence_provenance(placements: Iterable[Placement]) -> dict[str, Any]:
    """How much of an offline classification the statements themselves chose.

    Reported because the area link cannot carry it. Every kind with more than
    one candidate area gets placed, so a run that placed everything at ``low``
    and one that placed everything at ``high`` are indistinguishable from the
    assigned count alone — and only the second is evidence that the text was
    read. Omitted entirely when nothing was placed offline, so a fully reviewed
    run does not carry an empty histogram.
    """

    counts: Counter[str] = Counter(placement.confidence for placement in placements)
    return {"offline_confidence": dict(sorted(counts.items()))} if counts else {}


class UnsupportedRoleError(RuntimeError):
    """The run names a role this worker cannot execute.

    Unreachable through :class:`AgentRole` today — all three authorised roles
    have an execution path. It stays as the guard for a fourth appearing without
    one, because failing loudly beats succeeding a run that did nothing.
    """

    error_code = "role_not_implemented"


class MissingRunInputError(RuntimeError):
    """The run does not name what to work on."""

    error_code = "missing_run_input"


@dataclass(frozen=True, slots=True)
class AgentStepExecutor:
    """Executes one claimed run to completion in a single step.

    One step, not many: extraction is a single provider call and the write is one
    transaction, so there is no useful place to checkpoint in between. Multi-step
    runs remain supported by the worker — this executor simply does not need
    them, and inventing intermediate checkpoints would add recovery states with
    nothing to recover.
    """

    session_factory: sessionmaker[DbSession]
    extractor: ExtractionPort
    reviewer: ReviewPort | None = None
    """The review engine, or ``None`` for offline unambiguous-only classification.

    Optional on purpose. A deployment without a review provider still runs
    review runs; it simply classifies less, which is the honest outcome rather
    than a failed run.
    """

    def __call__(self, run: AgentRun, checkpoint: dict[str, Any]) -> StepResult:
        memory = MemoryService(self.session_factory)

        # At-least-once means this step can run twice. If the previous attempt
        # committed its knowledge but died before the run was marked succeeded,
        # re-extracting would double the output — so replay returns what exists.
        existing = memory.knowledge_produced_by(run.id)
        if existing:
            return StepResult(
                checkpoint={"phase": "written", "items_written": len(existing)},
                done=True,
                output_summary={"items_written": len(existing), "replayed": True},
            )

        if run.role in {AgentRole.REQUIREMENTS, AgentRole.DISCOVERY}:
            # One path, two instructions. The role selects the prompt; the
            # extraction, the provenance chain, and the review model are
            # identical, and duplicating the method to change one argument
            # would give the two ways to drift apart.
            return self._extract_from_message(memory, run)
        if run.role is AgentRole.ARCHITECTURE:
            return self._architecture(memory, run)
        if run.role is AgentRole.REVIEW:
            return self._review(run)
        raise UnsupportedRoleError(  # pragma: no cover - the enum has three members
            f"the {run.role.value} agent is not implemented; run {run.id} cannot be executed"
        )

    def _extract_from_message(self, memory: MemoryService, run: AgentRun) -> StepResult:
        """Extract candidates from the message the run names.

        Prefers ``message_id`` over inline text: the stored message is the
        verbatim source evidence, and extracting from a copy passed through the
        API would break the provenance chain the product exists to show.
        """

        context = run.input_context or {}
        message_id = context.get("message_id")
        source_text = context.get("source_text")
        from_message: MessageId | None = None

        if message_id:
            message = memory.get_message(MessageId(str(message_id)))
            if message is None:
                raise MissingRunInputError(f"unknown message: {message_id}")
            source_text = message.content
            from_message = message.id
        if not source_text:
            raise MissingRunInputError(
                f"a {run.role.value} run needs input_context.message_id or "
                f"input_context.source_text"
            )

        # A fan-out sets the breadth per chunk; a single message uses the
        # default. Reading it from the run rather than from configuration keeps
        # one document's policy attached to the runs it created.
        max_items = int(context.get("max_items") or DEFAULT_MAX_ITEMS_PER_CHUNK)
        result = self.extractor.extract(
            ExtractionRequest(
                role=run.role,
                source_text=str(source_text),
                max_items=max_items,
            )
        )
        return self._write(
            memory,
            run,
            [
                WriteKnowledgeRequest(
                    kind=item.kind.value,
                    content=item.content,
                    source=item.source_quote,
                    from_message_id=from_message,
                )
                for item in result.items
            ],
            {
                "items_written": len(result.items),
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
            },
        )

    def _architecture(self, memory: MemoryService, run: AgentRun) -> StepResult:
        """Derive decisions from confirmed knowledge only.

        A project with nothing confirmed yields no decisions rather than
        speculative ones. Retrieval records consumption, so "which run used this
        knowledge?" stays answerable relationally afterwards.
        """

        confirmed = memory.retrieve_knowledge(
            run.project_id, lifecycle=LifecycleState.VALIDATED, used_by_run_id=run.id
        )
        if not confirmed:
            return StepResult(
                checkpoint={"phase": "written", "items_written": 0},
                done=True,
                output_summary={"items_written": 0, "reason": "no_confirmed_knowledge"},
            )

        bodies = tuple(item.current_version.content for item in confirmed)
        result = self.extractor.extract(
            ExtractionRequest(
                role=AgentRole.ARCHITECTURE,
                source_text="\n".join(bodies),
                context=bodies,
            )
        )
        return self._write(
            memory,
            run,
            [
                WriteKnowledgeRequest(
                    kind=item.kind.value, content=item.content, source=item.source_quote
                )
                for item in result.items
            ],
            {
                "items_written": len(result.items),
                "consumed_items": len(confirmed),
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
            },
        )

    def _review(self, run: AgentRun) -> StepResult:
        """Classify what can be classified, and report what is wrong.

        One review path, two engines. Without a review adapter the run
        classifies only kinds accepted by exactly one area — no judgement, no
        invented coverage. With one configured, the same step asks a model for
        the ambiguous cases, which is the discrimination a model is actually
        for. The worker owns the run either way, so a review keeps its lease,
        its checkpoint, and its recovery.

        The one authoritative write a review run performs is an area link,
        stamped with the run that proposed it — reversible, attributable, and
        unable to invent coverage, because an area still needs *confirmed*
        knowledge of an accepted kind to become sufficient.

        Neither engine records contradictions. They report candidates and a
        human records one, because an unresolved contradiction on a mandatory
        area blocks readiness: a false positive would stall a project on a
        model's say-so. Flagging costs a reader a moment; recording costs the
        project its gate (ADR-0015).
        """

        readiness = ReadinessService(self.session_factory)
        review = ReviewService(self.session_factory)
        memory = MemoryService(self.session_factory)

        existing = {str(link.knowledge_item_id) for link in readiness.area_links(run.project_id)}
        candidates = [
            item
            for item in memory.retrieve_knowledge(run.project_id, lifecycle=None)
            if str(item.id) not in existing
        ]

        proposals, engine, provenance = self._classify(candidates)

        assigned = 0
        rejected: list[dict[str, str]] = []
        for item_id, area_key in proposals:
            try:
                readiness.assign_area(run.project_id, item_id, area_key, run.id)
            except (DomainInvariantError, LookupError) as error:
                # An area only counts kinds it declares. One impossible pairing
                # is a bad call, not an invalid review, and failing here would
                # discard every sound assignment made before it.
                rejected.append(
                    {"knowledge_id": str(item_id), "area_key": area_key, "reason": str(error)}
                )
                continue
            assigned += 1

        found = review.findings(run.project_id)
        summary: dict[str, Any] = {
            "areas_assigned": assigned,
            "rejected_assignments": rejected,
            "findings": len(found),
            "critical_findings": sum(1 for f in found if f.severity is Severity.CRITICAL),
            # Findings are derived, so the run records how many it saw rather
            # than a copy that could disagree with the state later.
            "classification": engine,
        }
        summary.update(provenance)

        # Recalculate, here, rather than leaving it to whoever reads next.
        #
        # Area links are what readiness counts, so a review that assigns them
        # and stops has changed nothing a person can see. The deployed project
        # held a snapshot at revision 0 against a current revision of 25 and
        # reported "0% · not_started" — accurate about a state twenty-five
        # revisions old, and flagged `is_stale` in a field no surface rendered.
        #
        # A snapshot is appended, not replaced, which is what lets the product
        # show readiness *moving* as knowledge lands.
        snapshot = readiness.calculate(run.project_id)
        summary["readiness_percentage"] = snapshot.percentage
        summary["readiness_status"] = snapshot.status.value

        return StepResult(
            checkpoint={"phase": "reviewed", "assigned": assigned},
            done=True,
            output_summary=summary,
        )

    def _classify(
        self, candidates: Sequence[KnowledgeItem]
    ) -> tuple[tuple[tuple[KnowledgeItemId, str], ...], str, dict[str, Any]]:
        """Return area proposals, which engine produced them, and its provenance.

        **In batches**, because one request per project does not survive a real
        one. A live deployment sent all 178 of a project's statements in a single
        call and got `provider_timeout` — not bad luck, but what this did on any
        project past a certain size, with certainty rising as the project grew.
        The project that most needs classification was the least able to get it.

        A reviewer failure falls back to the offline classifier rather than
        failing the run. Losing the ambiguous cases costs coverage a human can
        still supply; losing the run costs the unambiguous ones too. Batching
        makes that fallback *partial*: one failed batch no longer costs the
        model's judgement on the other five.

        What it returns is honest about which engine produced what. A run that
        degraded silently reported `succeeded` with a fixture's coverage, and
        readiness then reported a number derived from it — the same class of
        quiet wrongness as a stale snapshot rendered as current.
        """

        if self.reviewer is None or not candidates:
            placements = classify_offline_by_content(candidates)
            return (
                tuple((item_id, placement.area_key) for item_id, placement in placements),
                "offline_by_content",
                _confidence_provenance(placement for _, placement in placements),
            )

        area_keys = tuple(area.key for area in SOFTWARE_TEMPLATE.areas)
        batch_size = review_batch_size()

        proposals: list[tuple[KnowledgeItemId, str]] = []
        contradictions = 0
        degraded: list[str] = []
        reviewed_batches = 0
        provenance: dict[str, Any] = {}
        fallback_placements: list[Placement] = []

        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            request = ReviewRequest(
                statements=tuple(
                    ReviewedStatement(
                        knowledge_id=item.id, kind=item.kind, text=item.current_version.content
                    )
                    for item in batch
                ),
                area_keys=area_keys,
            )
            try:
                result = self.reviewer.review(request)
            except ExtractionError as error:
                # This batch only. The offline classifier still places what it
                # can within it, and the batches that succeeded keep the
                # judgement they were given.
                degraded.append(error.error_code)
                fallback = classify_offline_by_content(batch)
                fallback_placements.extend(placement for _, placement in fallback)
                proposals.extend((item_id, placement.area_key) for item_id, placement in fallback)
                continue

            reviewed_batches += 1
            proposals.extend(
                (finding.subject_id, finding.area_key)
                for finding in result.findings
                if finding.kind is ReviewFindingKind.AREA_CLASSIFICATION and finding.area_key
            )
            contradictions += sum(
                1 for finding in result.findings if finding.kind is ReviewFindingKind.CONTRADICTION
            )
            # Last writer wins, and they agree: every batch goes to the same
            # adapter with the same prompt.
            provenance = {
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
            }

        batches = reviewed_batches + len(degraded)
        # **What reviewed it, not merely that something did.** A fixture is a
        # `ReviewPort` like any other, so a run against recorded payloads
        # reported `reviewed_by_model` and readiness carried that word out to a
        # reader — `DeterministicReviewAdapter`'s own docstring says so, and
        # nothing acted on it. Same substitution as `semantic` on rule-based
        # output (`AUD-007`), one layer up (`AUD-039`).
        judged = "model" if judges(self.reviewer) else "fixture"
        if not reviewed_batches:
            engine = "offline_by_content_after_reviewer_error"
        elif degraded:
            engine = f"partially_reviewed_by_{judged}"
        else:
            engine = f"reviewed_by_{judged}"

        return (
            tuple(proposals),
            engine,
            {
                # Reported, never recorded. A human decides whether a proposed
                # conflict becomes a gate (ADR-0015).
                "proposed_contradictions": contradictions,
                "batches": batches,
                "batches_degraded": len(degraded),
                # The codes, not just the count. "which failure" is the first
                # question asked, and a count cannot answer it.
                "reviewer_errors": sorted(set(degraded)),
                **_confidence_provenance(fallback_placements),
                **provenance,
            },
        )

    def _write(
        self,
        memory: MemoryService,
        run: AgentRun,
        requests: Sequence[WriteKnowledgeRequest],
        summary: dict[str, Any],
    ) -> StepResult:
        """Write knowledge without completing the run.

        ``complete_run=False`` matters: the worker completes the run when the
        step reports done, and two callers succeeding the same run is an illegal
        transition, not a redundant one.
        """

        memory.write_knowledge(run.id, requests, complete_run=False)
        return StepResult(
            checkpoint={"phase": "written", "items_written": len(requests)},
            done=True,
            output_summary=summary,
            follow_up=self._review_when_the_queue_drains(memory, run),
        )

    def _review_when_the_queue_drains(
        self, memory: MemoryService, run: AgentRun
    ) -> tuple[FollowUp, ...]:
        """Ask for a review pass, but only once this is the last run standing.

        Attached to every run that writes knowledge, not to extraction alone.
        Architecture writes decisions, and decisions need an area like anything
        else — "knowledge written and never classified" is the same defect
        whichever role wrote it.

        **Extraction writes knowledge; review is what assigns it to an area, and
        readiness counts per area.** Without review a project holding hundreds
        of accurate statements reports 0% with every area empty — which is what
        a real deployment did for twenty-five knowledge revisions, because
        enqueuing review was left to a caller and no caller existed.

        Review is cross-chunk: chunk 7 and chunk 31 may conflict and neither run
        can see the other. So it is worth doing once, at the end, rather than
        after each chunk — hence the check that nothing else is still in
        flight. This run is not terminal yet (the worker completes it after this
        returns), so it is excluded by identity rather than by status.

        The race is real and handled by the key rather than by this check: two
        final runs can each see the other absent and both propose. An identical
        key makes that one review.
        """

        outstanding = [
            other
            for other in memory.runs_for_project(run.project_id)
            if other.id != run.id and not other.is_terminal
        ]
        if outstanding:
            return ()

        # Keyed on the revision, so a project that grows later is reviewed
        # again while a retried step is not. Keying on the run id would review
        # once per chunk; keying on the project alone would review once ever.
        revision = ReadinessService(self.session_factory).knowledge_revision(run.project_id)
        return (
            FollowUp(
                role=AgentRole.REVIEW,
                idempotency_key=f"review:after-extraction:r{revision}",
            ),
        )


#: Statements per review request.
#:
#: Forty because the failure it prevents was a 178-statement call timing out,
#: and because area classification is per-statement work: the model needs the
#: statement and the ten area names, not the rest of the project. A larger batch
#: buys fewer round trips and risks the thing that broke; a much smaller one
#: multiplies calls for judgement that does not improve.
#:
#: Not a hard limit — a default. `KAE_REVIEW_BATCH` overrides it for a
#: deployment whose provider has different patience.
DEFAULT_REVIEW_BATCH = 40


def review_batch_size(environ: dict[str, str] | None = None) -> int:
    """Return the statements-per-review-request size.

    Refuses a nonsensical value rather than clamping it. A deployment that set
    `KAE_REVIEW_BATCH=0` meant something, and silently substituting 40 would
    leave it believing its setting applied.
    """

    env = os.environ if environ is None else environ
    raw = (env.get("KAE_REVIEW_BATCH") or "").strip()
    if not raw:
        return DEFAULT_REVIEW_BATCH
    try:
        size = int(raw)
    except ValueError:
        raise ValueError(f"KAE_REVIEW_BATCH must be a whole number, not {raw!r}") from None
    if size < 1:
        raise ValueError(f"KAE_REVIEW_BATCH must be at least 1, not {size}")
    return size


def default_reviewer(build_bedrock: Callable[[], ReviewPort] | None = None) -> ReviewPort | None:
    """Return the review engine named by the environment.

    ``KAE_REVIEW=deterministic`` gives the offline fixture, which classifies
    only where a kind leaves no choice — and therefore populates two discovery
    areas out of ten on a real project. ``KAE_REVIEW=off`` disables the engine
    entirely. ``KAE_REVIEW=bedrock`` is the live adapter (EM-6b), which is what
    a deployment wants if readiness is to describe more than a fifth of the
    taxonomy.
    """

    setting = os.environ.get("KAE_REVIEW", "deterministic").strip().lower()
    if setting in {"off", "none", ""}:
        # No profile check. A disabled capability reaches nothing, and refusing
        # `off` would be the runtime profile ruling on product scope rather than
        # on what this deployment may reach (`D-172`).
        return None
    if setting == "deterministic":
        runtime_profile.require(
            runtime_profile.Reach.IN_PROCESS, variable="KAE_REVIEW", value=setting
        )
        return DeterministicReviewAdapter()
    if setting != "bedrock":
        # **A whitelist, because the fallback was silent and expensive.**
        #
        # This read `if setting != "bedrock": return DeterministicReviewAdapter()`,
        # so `KAE_REVIEW=bedrok`, `claude`, `titan` or any other slip selected
        # the offline fixture — and the run then reported `reviewed_by_model`,
        # because the fixture is a `ReviewPort` like any other. An operator who
        # believed they had configured a model reviewer got the 16% ceiling and
        # nothing said so.
        #
        # `build_embedder` and `build_classifier` have always raised on an
        # unknown name, and the reviewer is the one whose silent fallback
        # changes a number a person reads (AUD-006). This comment used to say
        # the reviewer was the only one that fell through; `default_extractor`
        # did too, fifty lines below, until `D-173`.
        raise ProviderConfigurationError(
            f"unknown KAE_REVIEW={setting!r}. Valid: bedrock, deterministic, off"
        )

    runtime_profile.require(runtime_profile.Reach.HOSTED, variable="KAE_REVIEW", value=setting)

    if build_bedrock is not None:  # pragma: no cover - injected only by tests
        return build_bedrock()

    from kae_memory.agents.bedrock import BedrockReviewAdapter

    # Refuses rather than degrading, exactly as `default_extractor` does. A
    # reviewer that quietly fell back to the fixture would leave a deployment
    # believing it was classifying with a model while two areas of ten
    # populated — which is the state EM-6b exists to end, and the state that
    # took four real projects to notice.
    region = resolve_region()
    if not region:
        raise RuntimeError(
            "KAE_REVIEW=bedrock requires an AWS region via AWS_REGION, "
            "AWS_DEFAULT_REGION, or the active AWS profile."
        )

    # `KAE_REVIEW_MODEL`, then `KAE_EXTRACTION_MODEL`, then the default.
    #
    # Falling back to the extraction model is not tidiness: a deployment that
    # had to name a model for extraction had to do so because the default is
    # not offered in its region or to its account, and the same is true of
    # review. Without this, configuring extraction correctly and review not at
    # all produced a 403 naming a model nobody chose — which reads as a broken
    # adapter rather than a missing setting, and did.
    model = (
        os.environ.get("KAE_REVIEW_MODEL", "").strip()
        or os.environ.get("KAE_EXTRACTION_MODEL", "").strip()
    )
    if model:
        return BedrockReviewAdapter(region=region, model=model)
    return BedrockReviewAdapter(region=region)


def default_extractor(build_bedrock: Callable[[], ExtractionPort] | None = None) -> ExtractionPort:
    """Return the extractor named by the environment.

    **Deterministic by default.** The demonstrable path must not depend on a
    provider being reachable, on credentials, or on a bill — and a fixture
    adapter makes the workflow reproducible for anyone who clones the repository.
    Set ``KAE_EXTRACTION=ollama`` for a model on this machine, or ``bedrock``
    for the hosted one. A name that is none of the three raises rather than
    quietly giving the fixture (`D-173`).
    """

    # Blank reads as unset rather than joining the whitelist below (`D-173`). A
    # reviewer is optional and `KAE_REVIEW=` means `off`; extraction is not, and
    # failing a worker over a variable a shell script exported conditionally
    # would refuse a deployment that wanted the documented default.
    chosen = os.environ.get("KAE_EXTRACTION", "").strip().lower() or "deterministic"

    # A model on this machine (`ADR-0006`). Named explicitly rather than made
    # the default: the fixture adapter is what keeps `python -m kae_memory.worker`
    # demonstrable on a clone with nothing installed, and silently swapping it
    # for a provider that may not be running would trade one surprise for
    # another.
    if chosen == "ollama":
        from kae_memory.agents.ollama_extraction import OLLAMA_URL, OllamaExtractionAdapter

        # `KAE_OLLAMA_URL` says where Ollama is, for this door as for the
        # embedder, the classifier and the goal judge — it reached three of the
        # four until `D-183`. The reach is read from the URL this adapter is
        # actually handed rather than assumed to be loopback, so the profile
        # cannot permit a call the adapter then makes somewhere else (`D-172`).
        base_url = os.environ.get("KAE_OLLAMA_URL", OLLAMA_URL).strip() or OLLAMA_URL
        runtime_profile.require(
            runtime_profile.reach_of_url(base_url),
            variable="KAE_EXTRACTION",
            value=chosen,
        )
        model = os.environ.get("KAE_EXTRACTION_MODEL", "").strip()
        if model:
            return OllamaExtractionAdapter(base_url=base_url, model=model)
        return OllamaExtractionAdapter(base_url=base_url)

    if chosen == "deterministic":
        runtime_profile.require(
            runtime_profile.Reach.IN_PROCESS, variable="KAE_EXTRACTION", value=chosen
        )
        return DeterministicExtractionAdapter()

    if chosen != "bedrock":
        # **The whitelist `default_reviewer` has, for the same reason** (`D-173`).
        # This read `if chosen != "bedrock": return DeterministicExtractionAdapter()`,
        # so `KAE_EXTRACTION=bedrok` or `ollam` selected the fixture, the run
        # succeeded, knowledge was written, and nothing said the model an
        # operator configured had never been called. The reviewer's comment
        # below claims only the reviewer fell through; it did not.
        raise ProviderConfigurationError(
            f"unknown KAE_EXTRACTION={chosen!r}. Valid: bedrock, ollama, deterministic"
        )

    runtime_profile.require(runtime_profile.Reach.HOSTED, variable="KAE_EXTRACTION", value=chosen)

    if build_bedrock is not None:  # pragma: no cover - injected only by tests
        return build_bedrock()

    from kae_memory.agents.bedrock import BedrockExtractionAdapter

    # A correctly configured AWS profile is enough on its own. Demanding
    # AWS_REGION when ~/.aws/config already carries one makes a valid
    # configuration look broken, which is the defect this resolves.
    region = resolve_region()
    if not region:
        raise RuntimeError(
            "KAE_EXTRACTION=bedrock requires an AWS region via AWS_REGION, "
            "AWS_DEFAULT_REGION, or the active AWS profile."
        )

    # `KAE_EXTRACTION_MODEL` overrides the default, because model availability
    # is regional and the default is not offered everywhere. A deployment in a
    # region without it fails at the first extraction with a validation error
    # naming a model nobody chose, which reads as a broken adapter rather than
    # a regional gap. Listing what a region offers is one CLI call; guessing is
    # not.
    model = os.environ.get("KAE_EXTRACTION_MODEL", "").strip()
    if model:
        return BedrockExtractionAdapter(region=region, model=model)
    return BedrockExtractionAdapter(region=region)
