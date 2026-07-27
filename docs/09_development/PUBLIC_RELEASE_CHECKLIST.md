# Public Release Checklist

**Status:** approved, 2026-07-27.

What the public release package must contain. Judging assets do not need to be
built first, but they cannot be left until the final day — each item below names
the milestone by which it must exist.

## Repository

| Item | Status | Due |
| --- | --- | --- |
| Complete source | present | — |
| `LICENSE` | present (Apache-2.0) | — |
| `README.md` with purpose, architecture, and quick start | present, extend as the product grows | M9 |
| Architecture diagram | not started | M9 |
| Local development instructions | partial — `make install`, `make check` | M5 |
| AWS deployment instructions | not started | M10 |
| `.env.example` sample configuration | not started | M5 |
| Synthetic demo data and seed command | not started | M9 |
| Reset and cleanup command | not started | M10 |
| Test commands | present — `make check` | — |
| Security notes | not started | M10 |
| Known limitations | not started | M11 |
| Release tag | not started | M11 |

## Judging assets

| Item | Due | Note |
| --- | --- | --- |
| Reporting screen | M9 | generated from operational data, not a separate analytics build |
| Screenshots | M9 | captured as each screen lands, not retrospectively |
| Demo script | M9 | from [`../05_product/UNIFIED_DEMO_NARRATIVE.md`](../05_product/UNIFIED_DEMO_NARRATIVE.md) |
| Architecture visuals | M10 | reuse the deployment diagram |
| Presentation deck | M11 | one story: an agent dies, another resumes |
| Demo video | M11 | must show recovery, not only the happy path |
| Devpost narrative | M11 | problem, proof, why CockroachDB and AWS are necessary |
| Setup instructions verified from a clean checkout | M11 | someone other than the author performs it |

## Security notes must cover

- what data the system stores and where;
- credential handling, local and deployed;
- the MCP inspection-only boundary and why it exists;
- the least-privilege database roles;
- what is deliberately absent — no authentication, no tenancy isolation, single
  trusted operator — stated plainly rather than implied.

## Known limitations must state

- persistence and retrieval scale are unmeasured;
- three fixed agent roles, no general agent hosting;
- no authentication, teams, billing, or administration;
- single-region demonstration deployment;
- extraction quality is unmeasured and human confirmation is required.

Honest limitations are more credible than silence. Judges find the gaps anyway.

## Release gate

The package is complete when a reviewer who has never seen the project can clone
the repository, follow the documented setup, run the tests, start the
application, and reproduce the demo narrative against seeded data — without
asking the author a question.
