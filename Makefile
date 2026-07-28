TEST_DB_CONTAINER ?= kae-crdb-test
TEST_DB_VERSION   ?= v26.2.1
TEST_DB_PORT      ?= 26258

.PHONY: install lint format-check typecheck test check migrate migrate-down test-db-up test-db-down test-db-logs api worker

install:
	uv sync --extra dev --extra api

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy

# Tests run against CockroachDB, never SQLite (ADR-0011). `test` starts the
# local node if it is not already running, so a fresh clone needs one command.
test: test-db-up
	uv run pytest

test-db-up:
	@docker inspect -f '{{.State.Running}}' $(TEST_DB_CONTAINER) 2>/dev/null | grep -q true || { \
		docker rm -f $(TEST_DB_CONTAINER) >/dev/null 2>&1 || true; \
		echo "starting CockroachDB $(TEST_DB_VERSION) on port $(TEST_DB_PORT)"; \
		docker run -d --name $(TEST_DB_CONTAINER) -p $(TEST_DB_PORT):26257 \
			cockroachdb/cockroach:$(TEST_DB_VERSION) \
			start-single-node --insecure --store=type=mem,size=1GiB >/dev/null; \
		until docker exec $(TEST_DB_CONTAINER) ./cockroach sql --insecure -e "SELECT 1" >/dev/null 2>&1; \
			do sleep 1; done; \
		echo "ready"; }

test-db-down:
	@docker rm -f $(TEST_DB_CONTAINER) >/dev/null 2>&1 && echo "stopped" || echo "not running"

test-db-logs:
	@docker logs --tail 50 $(TEST_DB_CONTAINER)

check: lint format-check typecheck test

migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade base

# Serves the same application `python -m kae_memory.api` serves. Needs
# KAE_DATABASE_URL; binds to loopback unless KAE_API_HOST says otherwise,
# because the API has no authentication (ADR-0014).
api:
	uv run python -m kae_memory.api

# The durable worker, as a separate process from the API (ADR-0013). Needs
# KAE_DATABASE_URL. Uses the offline extractor unless KAE_EXTRACTION=bedrock.
worker:
	uv run python -m kae_memory.worker
