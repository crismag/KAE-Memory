# Project Brief

## Executive summary

KAE-Memory is an **engineering memory operating system**: the durable, shared,
provenance-aware knowledge layer that lets humans and specialised AI agents work
on the same software project across sessions without losing what was decided,
why it was decided, or what evidence supported it.

That system is demonstrated through an **AI product-discovery workspace**. A user
arrives with an incomplete idea and a paragraph of description. Through targeted
questions, visible knowledge growth, and human confirmation, they leave with
validated requirements, recorded decisions, explicit unknowns, and a traceable
development blueprint.

```text
Engineering Memory Operating System
  -> First product: AI Product Discovery Workspace
  -> Proven by: Persistent Engineering Memory
  -> Delivered as: Blueprint Generation
```

The workspace is the visible product. The memory system is the durable asset.
The blueprint is what the user takes away. This chain resolves the apparent shift
in product identity: the workspace is not a change of direction, it is the first
product built on the memory system, and the vehicle that proves it.

## Problem

AI coding assistants are session-oriented. Long-running projects suffer from lost
context, repeated explanation, fragmented requirements, architectural drift, and
weak coordination between different AI tools. Software ideas begin as
conversations, notes, and partially formed decisions; important details are lost
between meetings and sessions, contradictions go unnoticed, and later agents
inherit incomplete or stale context.

## Intended users

- Independent software developers
- AI-assisted developers
- Engineering teams
- Solution architects
- Technical consultants
- Technical founders

The MVP targets one of these first: a technically capable founder, product owner,
analyst, architect, or developer with an incomplete idea and no
implementation-ready specification.

## Desired outcome

AI agents function as long-term engineering collaborators that retrieve and apply
project knowledge consistently across sessions rather than restarting from
isolated conversations. Every important statement carries its source, corrections
preserve history, and outputs trace back to confirmed evidence.

## Governance

The workflow is human-in-the-loop. Human owners retain product vision,
requirements validation, architecture approval, final technical decisions, and
quality assurance. Coding agents execute one bounded task at a time and report
evidence rather than expanding scope.

## Current phase

**Product Experience Alignment and Implementation Kickoff.** Specifications,
domain contracts, persistence foundations, product experience, demo narrative,
architecture context, and execution roadmap exist. Current work is the first
end-to-end product slice.

Milestone position, repository health, and the immediate next task are recorded
in [`CURRENT_PROJECT_STATE.md`](CURRENT_PROJECT_STATE.md), which should be read
before any other repository context.

## Product boundary

KAE-Memory is the durable shared-memory foundation plus the discovery experience
that proves it. The broader AI software engineering platform may later include
orchestration, code execution, review, testing, integrations, and autonomous
workflows. Those capabilities are not part of the first release; see
[`../05_product/MVP_SCOPE.md`](../05_product/MVP_SCOPE.md).
