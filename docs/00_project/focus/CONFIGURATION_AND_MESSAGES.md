# Focus Action — Configuration and Service Messages

## Outcome

Give KAE-Memory a small, validated backend settings system that replaces
behavior-changing magic values and duplicated service messages without adding a
UI, database-backed administration, or a broad policy framework.

## Scope

- Inventory executable Python and operational scripts for numeric and string
  literals that control limits, timeouts, retry/backoff, batches, token budgets,
  retrieval thresholds, dimensions, payload sizes, or response behaviour.
- Classify each finding before moving it.
- Inventory duplicated backend-generated messages in services, API, MCP, CLI,
  and worker code. Frontend copy belongs to KAE-Studio.
- Define version-controlled product defaults, environment overrides, validation,
  precedence, and effective-value source reporting.
- Migrate one coherent vertical slice first; pagination and response limits are
  a suitable proving slice because their contract is already tested by T4/T5.

## Placement rules

| Value | Placement |
| --- | --- |
| Safe product default | version-controlled YAML |
| Deployment/provider value | environment or secret manager |
| Runtime state | existing database/JSON only when operationally justified |
| Backend message | version-controlled message catalog with stable key |
| Protocol or mathematical constant | named constant near the code |
| Absolute security/resource ceiling | code, documented as non-overridable |

Each governed setting records a stable key, type, unit, default, allowed range or
choices, rationale, scope, override permission, reload/restart behaviour, and any
security, cost, or performance implication.

## Precedence

1. non-overridable coded boundary;
2. committed product default;
3. deployment/environment override;
4. future administrative override, only when explicitly authorised; and
5. future project/user override, only when explicitly authorised.

The first milestone implements only the layers currently needed. It must still
make the effective value and its source explainable.

## Not in scope

- settings or administration UI;
- role, approval, or governance workflows;
- storing every setting in the database;
- remote configuration service or universal hot reload;
- localisation beyond the present backend-message need;
- centralising test examples or harmless local literals mechanically.

## Acceptance criteria

- An auditable inventory and classification exists.
- A documented schema and precedence contract exists.
- Defaults and environment overrides are validated at the correct boundary.
- One coherent subsystem uses governed settings end to end.
- Invalid types and ranges fail clearly.
- Effective values can be traced to their source diagnostically.
- Selected backend messages use stable identifiers and parameterised templates.
- Secrets and non-overridable ceilings remain outside editable defaults.
- Existing MCP/API integrity fields and response contracts remain intact.
- Tests cover defaults, overrides, precedence, validation, and failure behaviour.

## First implementation instruction

Produce the inventory and proposed schema before editing behavior. Then implement
only one representative slice and run its contract tests plus the configuration
tests. Do not combine this with frontend deletion.

