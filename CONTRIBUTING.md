# Contributing

KAE-Memory uses specification-led, task-bounded development.

## Before changing code

1. Identify the approved requirement and architecture decision that justify the change.
2. Work from one issued task context in `development/tasks/`.
3. Confirm the task's allowed file scope and prohibited changes.
4. Record unresolved decisions rather than silently choosing them.

## Local setup

```bash
uv sync --extra dev
make check
```

## Pull request expectations

A pull request should include:

- requirement, ADR, and task identifiers;
- a concise description of behavioural change;
- tests for success, failure, and relevant boundaries;
- documentation updates when contracts or workflows change;
- a deviation report when implementation exposes a specification gap.

## Quality gate

All changes must pass Ruff linting and formatting checks, strict mypy checking,
and pytest. Passing automation does not replace review against the approved task
context and specifications.
