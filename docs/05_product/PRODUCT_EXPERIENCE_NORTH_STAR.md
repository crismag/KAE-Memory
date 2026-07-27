# KAE-Memory Product Experience North Star

**Status:** proposed product direction for MVP and hackathon demonstration.

## 1. Product identity

KAE-Memory is not presented to users as a database, agent framework, RAG system,
or generic chatbot.

> KAE-Memory is an AI product-discovery workspace that interviews a user, turns
> an incomplete software idea into validated engineering knowledge, remembers
> decisions across sessions, and produces a traceable development blueprint.

The product experience must make the growth of project knowledge visible.
CockroachDB and AWS enable the experience, but the user buys the outcome.

## 2. First target user

The MVP is designed for a technically capable founder, product owner, analyst,
architect, or developer who has an incomplete software idea but lacks a coherent,
implementation-ready specification.

The first user should be able to arrive with only a paragraph and leave with:

- a clearer product definition;
- identified users and workflows;
- confirmed requirements and decisions;
- visible unresolved gaps and contradictions;
- a generated, source-traceable development blueprint.

## 3. Value proposition

### User problem

Software ideas normally begin as conversations, notes, assumptions, and partially
formed decisions. Important details are lost between meetings and AI sessions.
Requirements are generated without enough evidence, contradictions are missed,
and later agents receive incomplete or stale context.

### Product promise

KAE-Memory progressively converts scattered input into durable project knowledge.
It asks the next highest-value question, shows what it has learned, preserves the
source of every important statement, and makes corrections without erasing history.

### Why users return

When the user returns in a later session, KAE-Memory continues from the real
project state rather than starting a new generic conversation.

The return experience should communicate:

- what was completed previously;
- what changed;
- what remains uncertain;
- the next highest-value action;
- what deliverables can now be generated.

## 4. Desired first 30 seconds

The first screen should avoid a complex dashboard. It should ask one direct
question:

```text
What are you building?

[ Describe your idea                                 ]

[ Start discovery ]
```

After submission, the workspace should immediately show:

- the user's idea captured as source evidence;
- initial project confidence or readiness;
- newly extracted actors, goals, constraints, or assumptions;
- important unknown areas;
- the first targeted follow-up question.

The user should understand the product before seeing an architecture diagram.

## 5. Core interaction model

The MVP workspace uses three coordinated areas:

```text
┌────────────────────┬─────────────────────────┬──────────────────────┐
│ Discovery          │ Current work            │ Project memory       │
│                    │                         │                      │
│ Conversation       │ Active question         │ Confirmed facts      │
│ Session history    │ Why it matters          │ Proposed facts       │
│ Source uploads     │ Answer controls         │ Unknowns             │
│                    │ Generation actions      │ Decisions and risks  │
└────────────────────┴─────────────────────────┴──────────────────────┘
```

Responsive versions may stack these areas, but the relationship must remain
clear: user input becomes visible memory and later becomes output.

## 6. Core user-visible concepts

### Project memory

The memory panel shows structured knowledge appearing as the conversation
progresses. Each item should display a type, status, source, and revision state.

Examples:

- Actor: Ministry coordinator
- Goal: Replace the physical reporting binder
- Rule: Reporting-cycle duration is configurable
- Constraint: Initial release supports one ministry organisation
- Unknown: Who approves a submitted report?

### Knowledge status

Use understandable labels:

- Proposed
- Confirmed
- Needs review
- Conflicting
- Superseded

Avoid presenting model confidence as certainty. Confidence may be visible as
supporting information but cannot replace confirmation status.

### Project readiness

Readiness is a directional indicator, not a scientific truth. It should reflect
coverage of required discovery areas and unresolved high-impact gaps.

The UI should explain why readiness changed. Example:

```text
Readiness increased from 46% to 58%

Resolved:
- Primary user identified
- Reporting-cycle rule confirmed

Still blocking blueprint generation:
- Approval workflow
- Access-control roles
```

### Traceability

Every important output should allow the user to navigate back to its evidence.
A requirement without a source should be labelled as an assumption requiring
confirmation.

## 7. Primary product journey

1. Create a project from an incomplete idea.
2. See initial knowledge and unknowns extracted.
3. Answer targeted discovery questions.
4. Confirm, reject, or revise proposed knowledge.
5. Leave and return in a later session.
6. Continue from durable project memory.
7. Search or inspect related decisions and sources.
8. Resolve a contradiction or supersede an outdated fact.
9. Generate a project blueprint.
10. Review traceability and export the output package.

## 8. Product proof moments

The interface must deliberately create these demonstration moments.

### Proof 1: Knowledge appears

The user submits a short idea and immediately sees structured project knowledge
and unresolved unknowns.

### Proof 2: The next question is purposeful

The interface explains which gap the question addresses and why it matters.

### Proof 3: Memory survives sessions

A later session recalls a prior decision and continues from the saved state.

### Proof 4: Corrections preserve history

The user changes a reporting rule. The previous item becomes superseded and the
new item becomes active, with both versions visible.

### Proof 5: Semantic retrieval is useful

Searching for a concept returns related conversation evidence, requirements,
decisions, document chunks, and generated sections.

### Proof 6: Output is grounded

The generated blueprint links its requirements and decisions back to confirmed
memory and source evidence.

## 9. MVP screens

The MVP requires only the following screens or views:

1. Start / create project
2. Discovery workspace
3. Memory explorer
4. Knowledge quality and audit
5. Blueprint viewer and export

Do not add administration, billing, marketplace, broad settings, team analytics,
or advanced visual knowledge graphs before the core journey works.

## 10. Product principles

1. Show knowledge growth, not hidden agent activity.
2. Ask one purposeful question at a time.
3. Preserve the user's exact source input.
4. Distinguish evidence, interpretation, and decision.
5. Make uncertainty visible.
6. Make corrections safe and reversible.
7. Make outputs traceable.
8. Hide infrastructure complexity from normal users.
9. Reveal technical proof only when useful for the demo or audit.
10. Prefer a complete, coherent journey over many disconnected features.

## 11. Non-goals

The MVP is not:

- a general-purpose chat assistant;
- a full project-management suite;
- an autonomous software factory;
- a source-code generation platform;
- a database administration product;
- a replacement for human approval.

## 12. Product acceptance criteria

The product experience is coherent when a first-time observer can answer these
questions after a three-minute demo:

- What problem does KAE-Memory solve?
- What does it remember?
- Why is that memory better than a normal chat history?
- How does the user correct the system?
- What concrete output does the user receive?
- Why are CockroachDB and AWS necessary to deliver the experience?
