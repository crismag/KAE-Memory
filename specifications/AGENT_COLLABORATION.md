# Agent Collaboration

**Status:** approved for the three MVP roles, 2026-07-27. Durable execution
contracts are in [`AGENT_EXECUTION_MODEL.md`](AGENT_EXECUTION_MODEL.md).

## Principle

Agents collaborate through explicit tasks, durable memory, typed artefacts, and reviewable state transitions. They do not coordinate by relying on hidden conversational context.

## Approved roles

Exactly three agent roles are authorised for the MVP (FR-009). Adding a fourth requires a new approved requirement.

- **Requirements agent:** converts discovery input into candidate requirements and explicit gaps.
- **Architecture agent:** derives coherent design from *confirmed* requirements, citing each one it uses.
- **Review agent:** retrieves requirements and decisions across sessions and reports unresolved gaps, contradictions, unsupported statements, and validation coverage. It proposes findings; it does not correct what it finds.
- **Human reviewer:** validates scope, requirements, decisions, conflicts, and quality. Confirmation is a human act — no agent confirms knowledge, including its own.

Deferred roles: research, planning, implementation, testing, and documentation agents.

## Agent contract

Each execution declares agent identity and version, role, project, task, allowed operations, input ContextBundle, expected output type, acceptance criteria, and escalation policy.

## Collaboration flow

1. A task is issued from approved project state.
2. Context is assembled for the role and task.
3. The agent returns typed contributions and a completion or deviation report.
4. Contributions remain proposed until validation policy is satisfied.
5. Review may validate, reject, request revision, or record a competing claim.
6. Accepted outputs become eligible for later retrieval.

## Permissions

Least privilege applies. Roles may have different read, propose, validate, supersede, and administrative permissions. Agents must not approve their own high-impact architecture or product decisions unless policy explicitly allows it.

## Escalation triggers

- Missing or contradictory requirements
- Required decision outside task scope
- Security or privacy uncertainty
- Architecture conflict
- Test failure that implies specification error
- Need to modify prohibited files or adjacent scope

## Observability

The platform should retain task identity, input bundle, tool actions where available, outputs, status transitions, errors, review result, and trace links.

## Write boundary

Agents write exclusively through KAE application contracts. No agent holds raw database credentials or issues SQL against domain tables. See ADR-0004 and [`../docs/06_architecture/MCP_ACCESS_POLICY.md`](../docs/06_architecture/MCP_ACCESS_POLICY.md).

## Resolved by the agent execution model

Retry rules, cancellation semantics, run status, and continuation are specified in [`AGENT_EXECUTION_MODEL.md`](AGENT_EXECUTION_MODEL.md).

## Open decisions

Delegation depth, concurrency controls, reviewer quorum, agent trust levels, and provider-specific isolation.
