.PHONY: install lint format-check typecheck test check migrate migrate-down

install:
	uv sync --extra dev

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint format-check typecheck test

migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade base
