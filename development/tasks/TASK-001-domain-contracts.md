# TASK-001 — Define Core Domain Contracts

**Status:** ready after ADR-0002 approval

## Objective

Introduce transport- and persistence-independent Python contracts for the first
persistent-memory vertical slice.

## Business purpose

Provide stable, testable domain language for project identity, agent identity,
knowledge submission, provenance, versioning, lifecycle state, and typed
relationships before database or API implementation begins.

## Related specifications

- `specifications/PRODUCT_REQUIREMENTS_SPECIFICATION.md`
- `specifications/DOMAIN_MODEL.md`
- `specifications/MEMORY_ARCHITECTURE.md`
- `specifications/API_CONTRACTS.md`
- `specifications/ADR/ADR-0001-memory-first.md`
- `specifications/ADR/ADR-0002-python-library-first-bootstrap.md`

## Expected outputs

- immutable or controlled domain value objects for identifiers and provenance;
- lifecycle-state enumeration and valid transition rules;
- project, agent, knowledge-item, knowledge-version, and relationship contracts;
- typed domain errors for invalid input and invalid transitions;
- unit tests for invariants, equality, transitions, and boundary failures;
- documentation of any specification gaps discovered.

## Constraints

- Domain code must not import FastAPI, SQLAlchemy, CockroachDB drivers, agent
  frameworks, or provider SDKs.
- Do not create database tables, migrations, endpoints, repositories, or runtime
  agents.
- Use explicit types and avoid unstructured dictionaries at domain boundaries.
- Preserve provenance and version history as first-class concepts.

## Allowed file scope

- `src/kae_memory/domain/`
- `tests/domain/`
- this task file for completion notes
- specification files only when recording an approved correction

## Prohibited changes

- persistence implementation;
- API or CLI implementation;
- semantic retrieval or embeddings;
- orchestration;
- deployment configuration;
- physical schema design.

## Acceptance criteria

1. A project, agent, and knowledge item can be represented without persistence or transport dependencies.
2. Every knowledge version requires source and actor provenance.
3. History is append-oriented; prior versions cannot be overwritten through the public contract.
4. Invalid lifecycle transitions return a typed domain error.
5. Relationships are typed and reference stable identifiers.
6. Unit tests cover valid and invalid construction and transitions.
7. `make check` passes.

## Definition of completion

Code, tests, and documentation are reviewed against the referenced
specifications. Any ambiguity is reported rather than resolved by scope
expansion.
