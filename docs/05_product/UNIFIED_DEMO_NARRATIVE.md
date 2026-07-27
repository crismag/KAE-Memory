# Unified Demo Narrative

**Status:** canonical, 2026-07-27. This is the single authoritative demo story.

Where this document and any other narrative disagree, this one governs.
[`DEMO_STORY_AND_SCRIPT.md`](DEMO_STORY_AND_SCRIPT.md) remains the source for
timing, sample data, and delivery craft.

## The one sentence

An agent begins work, writes durable engineering memory, disappears, and another
agent resumes in a later session without losing project knowledge — and the user
watches it happen in a discovery workspace, not a terminal.

## Product framing

The **discovery workspace** is the product. The user talks to it, confirms what
it learned, corrects it, and takes away a blueprint.

Three predefined agents operate **behind** the workspace, through KAE application
contracts and persistent engineering memory:

| Agent | Reads | Writes |
| --- | --- | --- |
| Requirements Agent | project brief, user messages | requirement knowledge, gaps |
| Architecture Agent | confirmed requirements | architecture decisions, derived from cited requirements |
| Review Agent | requirements and decisions | quality findings, conflicts, unresolved gaps |

The agents are not visible as a control dashboard. Their work surfaces as
knowledge appearing, questions being asked, and findings being raised. The user
never operates an agent directly.

This resolves the earlier divergence: the workspace is not being replaced by an
agent console, and the agent-collaboration proof is not a separate product. The
agents are how the workspace does its work.

## Demo sequence

Ten beats. Beats 5 to 8 are the ones that win the judging criterion — everything
before them is setup, everything after is evidence.

1. **Create project.** The user submits a paragraph describing an incomplete
   idea. It is persisted verbatim as source evidence before anything interprets
   it.
2. **Run the Requirements Agent.** Structured candidate knowledge appears in the
   workspace — actors, goals, rules, constraints, unknowns — each linked to the
   sentence that produced it.
3. **Validate requirements.** The user confirms, rejects, or revises. Confirmed
   knowledge becomes the durable baseline. The AgentRun that produced it is
   recorded.
4. **Run the Architecture Agent.** It retrieves the *confirmed* requirements —
   not the raw conversation — and writes architecture decisions that cite them.
5. **Simulate failure.** The worker is terminated mid-run. Nothing is lost;
   partial work is either committed or absent, never half-applied.
6. **Resume in a new session.** A new worker picks up the interrupted run from
   its durable state. The user sees continuation, not a restart.
7. **Run the Review Agent in that new session.** It retrieves requirements and
   decisions written by *other agents in earlier sessions* and reports gaps and
   conflicts.
8. **Show retrieval from CockroachDB.** Structured recall by project and status,
   with version and provenance intact across the session boundary.
9. **Show semantic recall.** A concept search returns related evidence,
   requirements, and decisions the user did not name exactly, with an explanation
   of why each result was included.
10. **Show provenance, audit timeline, and the final report.** Every statement in
    the generated blueprint traces back to confirmed knowledge and source
    evidence. A correction made earlier appears as superseded, not deleted.

## What the demo must prove

| Proof | Beat | Why it matters |
| --- | --- | --- |
| Knowledge is durable and typed | 2, 3 | Memory, not chat history |
| Provenance survives | 2, 10 | Claims are auditable |
| One agent reuses another's validated output | 4, 7 | Collaboration through memory |
| Work survives process death | 5, 6 | Durable workflow, disposable compute |
| Continuity crosses sessions | 6, 7, 8 | The core judging criterion |
| Recall is semantic, not just exact | 9 | The database earns its place |
| Corrections preserve history | 10 | Trustworthy evolution |
| Output is grounded | 10 | The user gets something real |

## What the demo must not become

- A happy-path chat transcript. **Recovery is the story.** If beats 5 and 6 are
  cut for time, the demo has lost its point.
- An agent-orchestration console. The user sees knowledge, not job queues.
- A database administration tour. CockroachDB is visible through what it makes
  possible, not through its console.
- A tour of every screen. Four beats of depth beat ten of breadth.

## Failure strategy

Each beat must have a fallback that keeps the narrative intact:

- seeded demo project available if creation fails;
- deterministic extraction fixtures if the model provider is unavailable;
- pre-recorded segment for the failure-and-resume beat if live termination is
  too risky on the day;
- static report export if generation fails.

A fallback that silently fakes durable memory is not acceptable — the recovery
beat must be real or explicitly labelled as a recording.

## Acceptance

The narrative is proven when a first-time observer can answer, after three
minutes: what KAE-Memory remembers, why that is better than chat history, what
happened when the agent died, how the user corrects the system, and what they
take away at the end.
