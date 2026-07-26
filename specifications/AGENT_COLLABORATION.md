# Agent Collaboration

**Status:** proposed protocol.

## Principle

Agents collaborate through explicit tasks, durable memory, typed artefacts, and reviewable state transitions. They do not coordinate by relying on hidden conversational context.

## Initial roles

- **Requirements agent:** converts validated discovery into testable requirements and gaps.
- **Architecture agent:** derives coherent design from approved requirements.
- **Human reviewer:** validates scope, requirements, decisions, conflicts, and quality.

Future roles may include research, planning, implementation, testing, review, and documentation agents.

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

## Open decisions

Delegation depth, concurrency controls, reviewer quorum, agent trust levels, retry rules, cancellation semantics, and provider-specific isolation.
