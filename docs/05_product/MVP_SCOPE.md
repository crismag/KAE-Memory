# MVP Scope

**Status:** proposed boundary; requires human approval.

## Product hypothesis

Specialised AI agents can collaborate more consistently on long-running software
engineering work when they share a persistent, provenance-aware project memory.

## First-release objective

Prove the hypothesis with one real, repeatable engineering workflow that crosses
session boundaries and uses more than one specialised agent.

## In-scope outcome

The release should demonstrate:

- durable project identity;
- persistent engineering knowledge;
- agent and source attribution;
- cross-session retrieval;
- reuse of prior requirements and decisions;
- visible traceability;
- explicit handling of corrections or conflicts;
- a multi-agent workflow whose result can be reviewed by a human.

These are proposed outcome categories, not yet approved implementation
requirements.

## Explicitly excluded until adopted

- Full autonomous software delivery
- Production user interface
- Billing and commercial account management
- Marketplace or plugin ecosystem
- Broad third-party integrations
- Multi-region production deployment
- General-purpose agent framework
- Automatic merging or deployment of generated code
- A universal knowledge graph for every domain
- Performance optimisation for unverified scale targets

## MVP success evidence

A reviewer can inspect a project started in one session, observe a second agent
retrieve and apply the first agent's validated work in another session, and
follow the provenance and trace links that explain why the later result was
produced.
