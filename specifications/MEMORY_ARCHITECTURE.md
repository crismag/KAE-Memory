# Memory Architecture

**Status:** proposed architecture principles.

## Memory definition

Memory is durable, attributable, versioned project knowledge that can be retrieved and reused by authorised humans and agents. Raw chat history alone is not project memory.

## Proposed memory classes

- **Evidence memory:** source observations and imported artefacts.
- **Specification memory:** requirements, constraints, interfaces, and acceptance criteria.
- **Decision memory:** approved choices and their rationale.
- **Execution memory:** tasks, runs, outcomes, errors, and validation evidence.
- **Experience memory:** reusable lessons and patterns derived from completed work.
- **Context memory:** reproducible records of what an agent was shown for a task.

## Lifecycle

`proposed -> validated -> active -> superseded`

Alternative exits include `rejected`, `withdrawn`, and policy-governed deletion. Transitions require actor attribution and a reason.

## Provenance

Each memory item should record project, creator, agent role, execution, source, creation time, content type, lifecycle state, version, and relevant trace relationships.

## Conflict handling

Contradictory contributions are retained as competing claims. The system must not silently select a winner. Resolution records the reviewing actor, rationale, and resulting state changes.

## Versioning and supersession

Updates create a new version or replacement item. The prior item remains addressable. Retrieval should distinguish current accepted state from historical versions.

## Human governance

Humans retain authority over product scope, requirement validation, architecture approval, sensitive-data policy, and final quality decisions. Agent confidence does not equal approval.

## Safety and quality controls

- Separate evidence from interpretation.
- Mark inferred or generated content.
- Do not persist secrets by default.
- Prevent retrieval of rejected or superseded content as current truth unless requested.
- Preserve enough metadata to reproduce context selection.

## Open decisions

Retention, deletion, legal holds, confidence semantics, validation permissions, merge rules, tenant isolation, and whether experience memory may cross project boundaries.
