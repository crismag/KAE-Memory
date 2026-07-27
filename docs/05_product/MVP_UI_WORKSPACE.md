# KAE-Memory MVP UI Workspace

**Status:** proposed interface contract for product validation and later implementation.

## 1. Purpose

This document defines the smallest appealing interface that can demonstrate the
KAE-Memory value proposition. It is intentionally technology-neutral until the
frontend stack is approved.

## 2. Navigation model

The MVP uses five top-level destinations:

1. Projects
2. Discovery
3. Memory
4. Quality
5. Blueprint

The active project remains visible in the application header. Avoid deep nested
navigation during the hackathon release.

## 3. Start and project creation

### Empty state

```text
KAE-Memory

Turn an incomplete software idea into validated project knowledge.

What are you building?
[                                                        ]

[ Start discovery ]
```

Optional supporting actions:

- Open existing project
- Try sample project

### Behaviour

Submitting the idea must:

- persist the exact source input;
- create the project and first session;
- start extraction visibly;
- route the user into the discovery workspace;
- show partial results as they become available.

## 4. Discovery workspace

### Desktop layout

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Project: Ministry Reporting System        Readiness: 58%             │
├───────────────────┬──────────────────────────┬───────────────────────┤
│ DISCOVERY         │ CURRENT WORK             │ PROJECT MEMORY        │
│                   │                          │                       │
│ Session timeline  │ Question                 │ Confirmed (8)         │
│ Conversation      │ Why this matters         │ Proposed (3)          │
│ Upload source     │ Related known facts      │ Unknowns (5)          │
│                   │ Answer field             │ Conflicts (1)         │
│                   │ [Submit answer]          │                       │
└───────────────────┴──────────────────────────┴───────────────────────┘
```

### Required interactions

- answer the active question;
- skip with a reason;
- mark a question not applicable;
- inspect the gap being addressed;
- confirm or reject newly proposed knowledge;
- open a source message;
- leave and resume the session.

### Processing states

The interface should show human-readable stages:

- Saving your answer
- Finding related project memory
- Extracting candidate knowledge
- Checking for conflicts
- Preparing the next question

Do not expose a blank spinner for the entire workflow.

## 5. Project memory panel

Memory items should use a compact card or row format.

```text
Business rule                         CONFIRMED
Reporting-cycle duration is configured per reporting category.
Source: Session 2, answer 4
Revised from: Two-week reporting cycle
[Open] [History]
```

### Filters

- All
- Confirmed
- Proposed
- Needs review
- Conflicting
- Superseded

### Types

- Goal
- Actor
- Workflow
- Requirement
- Rule
- Constraint
- Decision
- Assumption
- Risk
- Term

## 6. Memory explorer

The Memory destination provides search and relationship exploration.

### Search result grouping

Group related results by:

- Knowledge
- Conversations
- Documents
- Requirements
- Decisions
- Blueprint sections

Each result should show:

- why it matched;
- current status;
- source;
- project version;
- related records.

The user should be able to open a requirement and follow links backward to its
source evidence and forward to generated artefacts.

## 7. Quality and audit view

The Quality destination presents uncertainty without overwhelming the user.

### Summary cards

- Unresolved gaps
- Contradictions
- Unsupported outputs
- Assumptions requiring confirmation
- Memory audit findings

### Finding format

```text
HIGH — Conflicting reporting-cycle rules

Two active facts describe different cycle ownership.

Affected:
- Requirement FR-014
- Blueprint section: Scheduling model

[Review evidence] [Resolve]
```

The Memory Auditor action should clearly identify that a controlled system audit
is being performed. Do not present MCP as a user-facing product category.

## 8. Blueprint viewer

The Blueprint destination contains a document-style viewer with a section index.

Required sections:

- Product definition
- Target users
- User journeys
- Functional requirements
- Non-functional requirements
- Domain model
- Architecture summary
- Implementation phases
- Risks and open questions
- Traceability report

### Source indicator

Every generated statement should be classified as one of:

- Grounded in confirmed knowledge
- Derived from confirmed knowledge
- Assumption requiring confirmation

### Actions

- Generate or regenerate selected section
- Review changes
- Approve section
- Open sources
- Export package

## 9. Readiness indicator

Readiness must be explainable and resistant to superficial gamification.

It may combine weighted coverage of:

- problem and outcome;
- target users;
- key workflows;
- business rules;
- data and domain concepts;
- constraints;
- non-functional requirements;
- unresolved contradictions;
- traceability quality.

The UI must show the major contributors and blockers. Do not display a percentage
without an explanation panel.

## 10. Visual direction

The product should feel like an engineering workspace rather than a playful
consumer chatbot.

Recommended characteristics:

- clean document and workspace layout;
- restrained use of colour;
- strong status hierarchy;
- readable typography;
- clear source and revision cues;
- subtle progress motion when knowledge is added;
- accessible contrast and keyboard navigation.

Avoid:

- excessive gradients;
- animated agent avatars;
- dense infrastructure dashboards;
- unexplained technical badges;
- decorative graphs without user decisions attached.

## 11. Responsive behaviour

On smaller screens:

- show the Current Work panel first;
- make Discovery and Project Memory switchable tabs;
- keep the active question and answer action visible;
- preserve access to source and status details.

The hackathon demo should target a desktop browser first.

## 12. Empty, loading, error, and recovery states

Every main view must define:

- empty state;
- partial-data state;
- loading state;
- recoverable model failure;
- database or network failure;
- retry state;
- completed state.

A failed agent action must not erase the submitted answer. The UI should say that
the answer is safely stored and offer a retry for processing.

## 13. Accessibility baseline

- All actions are keyboard reachable.
- Status is not communicated by colour alone.
- Forms have explicit labels and validation messages.
- Dynamic processing updates use accessible announcements.
- Source links and revision history are navigable without a mouse.

## 14. UI acceptance criteria

The interface is ready for implementation when:

- all five destinations have defined primary actions;
- the three-panel discovery workspace can be wireframed without inventing new
  product rules;
- every knowledge status has visible user behaviour;
- readiness changes are explainable;
- source and revision navigation is defined;
- error recovery preserves user input;
- the demo story can be executed through the proposed views.
