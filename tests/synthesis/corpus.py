"""Conversation-derived extraction corpus used as the synthesis regression fixture.

Counts match KAE-Ecosystem ``00-MASTER-CONTEXT.md``: 47 goals, 22 actors, 15
rules, 13 assumptions, 12 requirements, 59 material unknowns. Constraints and
decisions are included because Phase 0 names conflicting decision/state as a
representative bad case; they are extra to the headline counts.

Semantic duplicates are worded differently so identical-statement collapse does
not erase the pathology. Exact synthesized counts are not an acceptance number.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from kae_memory.domain.models import KnowledgeKind

# Named regression cases. Synthesis later must handle each; exact output
# cardinality is not prescribed.
HOLD_MOON: Final = "hold-moon"
PLANNING_EXPERTISE: Final = "planning-expertise"
DEVELOPMENT_READY_PLAN: Final = "development-ready-plan"
ACTOR_USER_FLATTENING: Final = "actor-user-flattening"
PERSONA_AS_ACTOR: Final = "persona-as-actor"
AI_AS_ACTOR: Final = "ai-as-actor"
PARSER_SCAFFOLDING: Final = "parser-scaffolding"
WHAT_ARE_WE_BUILDING: Final = "what-are-we-building"
READINESS_CRITERIA: Final = "readiness-criteria"
CONFLICTING_STATE: Final = "conflicting-state"
TEMPORARY_WORKFLOW: Final = "temporary-workflow"
CONVERSATION_LOCAL: Final = "conversation-local"
MISCLASSIFIED: Final = "misclassified"
COLLABORATION_MVP: Final = "collaboration-mvp"

HOLD_MOON_TEXT: Final = "Hold something until it reaches the moon."
PROJECT_IDENTITY_TEXT: Final = (
    "KAE turns discussions and documents into a development-ready project definition."
)
AREA_SUFFICIENT_TEXT: Final = "Problem and value is sufficiently defined for the current stage."

HEADLINE_COUNTS: Final[Mapping[str, int]] = {
    KnowledgeKind.GOAL.value: 47,
    KnowledgeKind.ACTOR.value: 22,
    KnowledgeKind.RULE.value: 15,
    KnowledgeKind.ASSUMPTION.value: 13,
    KnowledgeKind.REQUIREMENT.value: 12,
    KnowledgeKind.UNKNOWN.value: 59,
}

ATTENTION_BOUND: Final = 8
"""Upper bound for a handful of genuine attention items. Not a target count."""


@dataclass(frozen=True, slots=True)
class ExtractedObservation:
    """One extracted row as the current product stores it."""

    kind: KnowledgeKind
    content: str
    source: str
    cases: frozenset[str]
    confirm: bool = False


def _obs(
    kind: KnowledgeKind,
    content: str,
    *cases: str,
    source: str | None = None,
    confirm: bool = False,
) -> ExtractedObservation:
    tag = source or f"conversation:{kind.value}:{content[:24]}"
    return ExtractedObservation(kind, content, tag, frozenset(cases), confirm)


_GOALS: tuple[ExtractedObservation, ...] = (
    _obs(
        KnowledgeKind.GOAL,
        "The product should not require the user to already know how to plan a software project.",
        PLANNING_EXPERTISE,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "People without planning expertise must still be able to use KAE.",
        PLANNING_EXPERTISE,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "KAE is for founders who have never written a project plan.",
        PLANNING_EXPERTISE,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "No prior planning training should be needed to get value from the product.",
        PLANNING_EXPERTISE,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "A first-time founder can produce a plan without becoming a project manager first.",
        PLANNING_EXPERTISE,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Planning literacy is not a prerequisite for using the product.",
        PLANNING_EXPERTISE,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Transform rough project material into a development-ready plan.",
        DEVELOPMENT_READY_PLAN,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Turn scattered notes into something a developer can implement.",
        DEVELOPMENT_READY_PLAN,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Convert incomplete ideas into an actionable plan.",
        DEVELOPMENT_READY_PLAN,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Produce a structured plan from messy inputs.",
        DEVELOPMENT_READY_PLAN,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Make the output useful enough to start development.",
        DEVELOPMENT_READY_PLAN,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Rough ideas should become a plan a coding agent can follow.",
        DEVELOPMENT_READY_PLAN,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "The outcome is a development-ready context package.",
        DEVELOPMENT_READY_PLAN,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Scattered documents become an implementation-ready definition.",
        DEVELOPMENT_READY_PLAN,
    ),
    _obs(KnowledgeKind.GOAL, HOLD_MOON_TEXT, HOLD_MOON),
    _obs(KnowledgeKind.GOAL, PROJECT_IDENTITY_TEXT),
    _obs(
        KnowledgeKind.GOAL,
        "Original source notes must be preserved.",
        MISCLASSIFIED,
    ),
    _obs(KnowledgeKind.GOAL, "The product must work on the web.", MISCLASSIFIED),
    _obs(
        KnowledgeKind.GOAL,
        "Users should be able to upload documents.",
        MISCLASSIFIED,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Every confirmation should be recorded.",
        MISCLASSIFIED,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "KAE should ask before making consequential decisions.",
        MISCLASSIFIED,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "In this conversation, wait for my next message before continuing.",
        CONVERSATION_LOCAL,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Use bullet points in the next reply.",
        CONVERSATION_LOCAL,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Remember what I said earlier in this chat.",
        CONVERSATION_LOCAL,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Don't ask me more than one question at a time in this session.",
        CONVERSATION_LOCAL,
    ),
    _obs(KnowledgeKind.GOAL, "Keep a durable record of project knowledge across sessions."),
    _obs(KnowledgeKind.GOAL, "A person should be able to revisit any planning area later."),
    _obs(KnowledgeKind.GOAL, "Generated packages must be usable without the original chat."),
    _obs(KnowledgeKind.GOAL, "The user remains free to navigate rather than follow a wizard."),
    _obs(KnowledgeKind.GOAL, "Evidence of where a statement came from must remain retrievable."),
    _obs(KnowledgeKind.GOAL, "Reduce the work of confirming extracted sentences one by one."),
    _obs(KnowledgeKind.GOAL, "Support a solo founder who later adds collaborators."),
    _obs(KnowledgeKind.GOAL, "Local execution should be sufficient to do useful work."),
    _obs(KnowledgeKind.GOAL, "Cloud providers are adapters, not the canonical runtime."),
    _obs(KnowledgeKind.GOAL, "Interviewing should feel like collaboration, not a form."),
    _obs(KnowledgeKind.GOAL, "Architecture should emerge after problem and value are clear."),
    _obs(KnowledgeKind.GOAL, "Modules should be derived from the project, not a template list."),
    _obs(KnowledgeKind.GOAL, "A coding agent can complete a bounded task from the package alone."),
    _obs(KnowledgeKind.GOAL, "Humans review the project, not KAE's internal notebook."),
    _obs(KnowledgeKind.GOAL, "Unknowns that have already been answered should not keep appearing."),
    _obs(KnowledgeKind.GOAL, "Repository ingestion must not flood the user with review cards."),
    _obs(KnowledgeKind.GOAL, "The product should recommend before it asks, when it can."),
    _obs(KnowledgeKind.GOAL, "Accepted decisions become inputs to later reasoning."),
    _obs(KnowledgeKind.GOAL, "The project story should stay short enough to read in seconds."),
    _obs(KnowledgeKind.GOAL, "Topic rooms should keep their conversation identity across visits."),
    _obs(
        KnowledgeKind.GOAL,
        "Home should say what the project is, not how many rows Memory holds.",
    ),
    _obs(KnowledgeKind.GOAL, "Quality attributes should be chosen, not left as an empty heading."),
)

_ACTORS: tuple[ExtractedObservation, ...] = (
    _obs(KnowledgeKind.ACTOR, "User", ACTOR_USER_FLATTENING),
    _obs(KnowledgeKind.ACTOR, "The user entering notes", ACTOR_USER_FLATTENING),
    _obs(
        KnowledgeKind.ACTOR,
        "The user accepting consequential decisions",
        ACTOR_USER_FLATTENING,
    ),
    _obs(KnowledgeKind.ACTOR, "Project owner", ACTOR_USER_FLATTENING),
    _obs(KnowledgeKind.ACTOR, "A person using KAE", ACTOR_USER_FLATTENING),
    _obs(KnowledgeKind.ACTOR, "Someone who confirms knowledge", ACTOR_USER_FLATTENING),
    _obs(KnowledgeKind.ACTOR, "First-time founder", PERSONA_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "Aspiring developer", PERSONA_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "Experienced developer", PERSONA_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "AI assistant", AI_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "KAE", AI_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "The interviewer agent", AI_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "A coding agent consuming the package", AI_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "GitHub MCP", AI_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "Ollama", AI_AS_ACTOR),
    _obs(KnowledgeKind.ACTOR, "Decision authority for scope"),
    _obs(KnowledgeKind.ACTOR, "Reviewer of generated packages"),
    _obs(KnowledgeKind.ACTOR, "Operator of the local deployment"),
    _obs(KnowledgeKind.ACTOR, "Domain expert contributing source material"),
    _obs(KnowledgeKind.ACTOR, "Tester who validates acceptance criteria"),
    _obs(KnowledgeKind.ACTOR, "Administrator of credentials and providers"),
    _obs(KnowledgeKind.ACTOR, "Downstream implementer receiving a work package"),
)

_RULES: tuple[ExtractedObservation, ...] = (
    _obs(KnowledgeKind.RULE, "A user preference is a rule."),
    _obs(KnowledgeKind.RULE, "KAE must not silently settle consequential decisions."),
    _obs(KnowledgeKind.RULE, "The browser must not hold provider credentials."),
    _obs(KnowledgeKind.RULE, "Memory must not become a blob warehouse."),
    _obs(KnowledgeKind.RULE, "Acquisition stays in Studio."),
    _obs(KnowledgeKind.RULE, "CIE must not maintain a parallel truth store."),
    _obs(KnowledgeKind.RULE, "Generated files must not overwrite unrelated user content."),
    _obs(
        KnowledgeKind.RULE,
        "Rejected knowledge must not be revived by a later identical extract.",
    ),
    _obs(KnowledgeKind.RULE, "Every knowledge version carries provenance."),
    _obs(KnowledgeKind.RULE, "Unattended merge of near-duplicates is not allowed yet."),
    _obs(KnowledgeKind.RULE, "Tests must not target the application database."),
    _obs(KnowledgeKind.RULE, "Offline is the canonical execution environment."),
    _obs(KnowledgeKind.RULE, "A progress percentage must not be invented from row ratios."),
    _obs(KnowledgeKind.RULE, "Internal identifiers are not user-facing content."),
    _obs(KnowledgeKind.RULE, "Defer is an explicit action, not the only control on an open item."),
)

_ASSUMPTIONS: tuple[ExtractedObservation, ...] = (
    _obs(
        KnowledgeKind.ASSUMPTION,
        "KAE is the name of the system under discussion.",
        PARSER_SCAFFOLDING,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "Prior conversation context still applies in this session.",
        PARSER_SCAFFOLDING,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "The speaker is referring to this product rather than a different KAE.",
        PARSER_SCAFFOLDING,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "The project has a single user for MVP.",
        COLLABORATION_MVP,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "Account ownership is individual rather than organisational.",
        COLLABORATION_MVP,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "Collaboration features can wait until after MVP.",
        COLLABORATION_MVP,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "The same person both defines the product and confirms decisions.",
        COLLABORATION_MVP,
    ),
    _obs(KnowledgeKind.ASSUMPTION, "Local disk is an acceptable source of repositories."),
    _obs(KnowledgeKind.ASSUMPTION, "A GitHub App will eventually replace pasted tokens."),
    _obs(KnowledgeKind.ASSUMPTION, "Ollama is available on the operator's machine."),
    _obs(KnowledgeKind.ASSUMPTION, "English is the working language of the project."),
    _obs(KnowledgeKind.ASSUMPTION, "The first generated package targets a coding agent."),
    _obs(KnowledgeKind.ASSUMPTION, "Voice intake is out of scope for the current slice."),
)

_REQUIREMENTS: tuple[ExtractedObservation, ...] = (
    _obs(KnowledgeKind.REQUIREMENT, "Original source notes must be preserved and retrievable."),
    _obs(KnowledgeKind.REQUIREMENT, "The product shall support web now and mobile later."),
    _obs(KnowledgeKind.REQUIREMENT, "A user can paste notes as a project source."),
    _obs(KnowledgeKind.REQUIREMENT, "A user can connect a local directory as a source."),
    _obs(KnowledgeKind.REQUIREMENT, "A user can connect a GitHub repository as a source."),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Uploaded documents become evidence after decode, not silent loss.",
    ),
    _obs(KnowledgeKind.REQUIREMENT, "Project Home summarises the project, not Memory counters."),
    _obs(KnowledgeKind.REQUIREMENT, "Workspace topic areas remain revisitable after completion."),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Attention items explain why they matter and what they affect.",
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Accepted decisions propagate to related unknowns and assumptions.",
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Generated context files are marked so they are not re-ingested as novel evidence.",
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Repository write failures must not lose accepted project knowledge.",
    ),
)

_UNKNOWNS: tuple[ExtractedObservation, ...] = (
    _obs(KnowledgeKind.UNKNOWN, "What are we building?", WHAT_ARE_WE_BUILDING),
    _obs(KnowledgeKind.UNKNOWN, "What product is this conversation about?", WHAT_ARE_WE_BUILDING),
    _obs(KnowledgeKind.UNKNOWN, "What problem are we discussing?", WHAT_ARE_WE_BUILDING),
    _obs(KnowledgeKind.UNKNOWN, "Which project is this?", WHAT_ARE_WE_BUILDING),
    _obs(KnowledgeKind.UNKNOWN, "Is this still the same software idea?", WHAT_ARE_WE_BUILDING),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What is the name of the thing being planned?",
        WHAT_ARE_WE_BUILDING,
    ),
    _obs(KnowledgeKind.UNKNOWN, HOLD_MOON_TEXT, HOLD_MOON),
    _obs(KnowledgeKind.UNKNOWN, "Hold the request until it reaches the moon.", HOLD_MOON),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What does development-ready mean for this project?",
        READINESS_CRITERIA,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "When is a plan development-ready?",
        READINESS_CRITERIA,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "How do we know the plan is development-ready?",
        READINESS_CRITERIA,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What makes output development-ready rather than merely documented?",
        READINESS_CRITERIA,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "When is a structured plan complete enough?",
        READINESS_CRITERIA,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What counts as an actionable plan?",
        READINESS_CRITERIA,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What does something useful mean as a completion criterion?",
        READINESS_CRITERIA,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "Who decides that planning is finished?",
        READINESS_CRITERIA,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "Is team collaboration in MVP?",
        COLLABORATION_MVP,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "Will more than one person confirm decisions in the first release?",
        COLLABORATION_MVP,
    ),
    _obs(KnowledgeKind.UNKNOWN, "Should classification run automatically after every turn?"),
    _obs(KnowledgeKind.UNKNOWN, "Where should domain synthesizers live — Memory or CIE?"),
    _obs(KnowledgeKind.UNKNOWN, "What Git workflow should context-file writes use?"),
    _obs(KnowledgeKind.UNKNOWN, "Is scanned-PDF OCR in the first upload slice?"),
    _obs(KnowledgeKind.UNKNOWN, "Which quality attributes matter for this product?"),
    _obs(KnowledgeKind.UNKNOWN, "What is the authority model for scope changes?"),
    _obs(KnowledgeKind.UNKNOWN, "How should tenancy be ordered against acquisition?"),
    _obs(KnowledgeKind.UNKNOWN, "Does Home need a change feed before synthesis exists?"),
    _obs(KnowledgeKind.UNKNOWN, "Should Discuss this remain visible on established topics?"),
    _obs(KnowledgeKind.UNKNOWN, "What is the bounded size of a human attention queue?"),
    _obs(KnowledgeKind.UNKNOWN, "May Memory merge near-duplicate statements unattended?"),
    _obs(KnowledgeKind.UNKNOWN, "What happens when repository persistence fails mid-decision?"),
    _obs(KnowledgeKind.UNKNOWN, "Are meeting transcripts a source kind in this slice?"),
    _obs(KnowledgeKind.UNKNOWN, "Should URL fetch be allowed in offline profile?"),
    _obs(KnowledgeKind.UNKNOWN, "Who consumes the development package first?"),
    _obs(KnowledgeKind.UNKNOWN, "What is out of scope for crazy_factory right now?"),
    _obs(KnowledgeKind.UNKNOWN, "How is module derivation triggered?"),
    _obs(KnowledgeKind.UNKNOWN, "What constitutes a blocking architecture conflict?"),
    _obs(KnowledgeKind.UNKNOWN, "When may an area be reopened after it was sufficient?"),
    _obs(KnowledgeKind.UNKNOWN, "Are personas distinct actors or variants of one user?"),
    _obs(KnowledgeKind.UNKNOWN, "Is GitHub MCP a stakeholder or a system?"),
    _obs(KnowledgeKind.UNKNOWN, "Should derived rules require a second human approval?"),
    _obs(KnowledgeKind.UNKNOWN, "What severity is actually critical versus merely open?"),
    _obs(KnowledgeKind.UNKNOWN, "Can the interviewer run entirely on a local model?"),
    _obs(KnowledgeKind.UNKNOWN, "What is the default planning/ directory root?"),
    _obs(KnowledgeKind.UNKNOWN, "How are KAE-managed files distinguished from user docs?"),
    _obs(KnowledgeKind.UNKNOWN, "Should attention items deep-link into topic rooms?"),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What is the recommendation when readiness criteria are undefined?",
    ),
    _obs(KnowledgeKind.UNKNOWN, "Does a solo project still need a RACI-like model?"),
    _obs(KnowledgeKind.UNKNOWN, "When does an assumption become a decision?"),
    _obs(KnowledgeKind.UNKNOWN, "How should cross-topic effects be explained in chat?"),
    _obs(KnowledgeKind.UNKNOWN, "Is a visual architecture editor in the first topic-room slice?"),
    _obs(KnowledgeKind.UNKNOWN, "What evidence is enough to close what-are-we-building?"),
    _obs(KnowledgeKind.UNKNOWN, "Should the moon sentence be deleted or retained as evidence?"),
    _obs(KnowledgeKind.UNKNOWN, "How many goal clusters are actually distinct outcomes?"),
    _obs(KnowledgeKind.UNKNOWN, "What is the trigger to re-run project-wide consistency?"),
    _obs(KnowledgeKind.UNKNOWN, "Are implementation context packages a later Artifacts job?"),
    _obs(KnowledgeKind.UNKNOWN, "What is the cost bound for incremental synthesis?"),
    _obs(KnowledgeKind.UNKNOWN, "Does the golden corpus itself need versioning?"),
    _obs(KnowledgeKind.UNKNOWN, "Who may override an accepted decision with new evidence?"),
    _obs(KnowledgeKind.UNKNOWN, "What happens to deferred attention items at package generation?"),
)

_CONSTRAINTS: tuple[ExtractedObservation, ...] = (
    _obs(
        KnowledgeKind.CONSTRAINT,
        "Team collaboration is outside MVP.",
        COLLABORATION_MVP,
    ),
    _obs(KnowledgeKind.CONSTRAINT, "Original user content must not be altered."),
    _obs(KnowledgeKind.CONSTRAINT, "Progression must not be rigid."),
)

_DECISIONS: tuple[ExtractedObservation, ...] = (
    _obs(
        KnowledgeKind.DECISION,
        AREA_SUFFICIENT_TEXT,
        CONFLICTING_STATE,
        confirm=True,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "Use Confirm or Reject on each extracted candidate.",
        CONFLICTING_STATE,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "In this session, skip architecture and stay on requirements.",
        TEMPORARY_WORKFLOW,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "Local-first execution is the canonical environment.",
    ),
)

OBSERVATIONS: tuple[ExtractedObservation, ...] = (
    _GOALS + _ACTORS + _RULES + _ASSUMPTIONS + _REQUIREMENTS + _UNKNOWNS + _CONSTRAINTS + _DECISIONS
)


def count_by_kind(observations: tuple[ExtractedObservation, ...] = OBSERVATIONS) -> dict[str, int]:
    """Return extracted-row counts by knowledge kind."""

    return dict(Counter(item.kind.value for item in observations))


def observations_for(*cases: str) -> tuple[ExtractedObservation, ...]:
    """Return observations tagged with any of the named regression cases."""

    wanted = frozenset(cases)
    return tuple(item for item in OBSERVATIONS if item.cases & wanted)


def collapse_key(observation: ExtractedObservation) -> tuple[str, str]:
    """Match Memory's identical-statement identity (kind + normalised text)."""

    return observation.kind.value, " ".join(observation.content.split()).casefold()


_HEADLINE_ACTUAL = {
    kind: count for kind, count in count_by_kind().items() if kind in HEADLINE_COUNTS
}
if dict(HEADLINE_COUNTS) != _HEADLINE_ACTUAL:
    raise RuntimeError(
        "golden corpus headline counts drifted: "
        f"expected {dict(HEADLINE_COUNTS)}, got {_HEADLINE_ACTUAL}"
    )
