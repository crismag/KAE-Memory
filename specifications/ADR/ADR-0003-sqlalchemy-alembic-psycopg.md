# ADR-0003 — SQLAlchemy, Alembic, and Psycopg Persistence

**Status:** accepted, 2026-07-27

## Context

KAE-Memory requires CockroachDB-backed persistence while preserving the transport- and persistence-independent domain contracts introduced by TASK-001. The persistence layer must support explicit mappings, migrations, transactions, and CockroachDB retry behaviour without making ORM classes the domain model.

## Decision

Use:

- SQLAlchemy 2.x for explicit relational mappings and repository implementation;
- Psycopg 3 as the PostgreSQL-compatible driver;
- Alembic for ordered schema migrations;
- application-managed bounded retry for CockroachDB serialization failures (`SQLSTATE 40001`);
- separate domain and persistence models with explicit mapping functions.

## Consequences

- Domain contracts remain free of SQLAlchemy imports.
- Schema changes must be represented by migrations.
- Repository operations execute inside caller-visible transaction boundaries.
- Retry logic must rerun the complete transaction callback, not individual statements with hidden partial state.
- Persistence tests may use SQLite for fast mapping checks, but CockroachDB integration tests remain the compatibility authority.

## Deferred

- multi-region locality strategy;
- tenant partitioning;
- vector and semantic indexes;
- changefeeds or outbox implementation;
- production pool sizing and deployment topology.