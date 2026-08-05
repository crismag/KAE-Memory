# Token Reduction, Verified — T5

Status: **verified with reservations**, 2026-08-05. Target T5 of
[`MCP_TARGET_CHECKLIST.md`](MCP_TARGET_CHECKLIST.md).

T1 measured the surface. T2, T2B, T3, and T4 reduced it. T5 asks the question
those four cannot answer about themselves: **did the reduction cost anything a
caller needed?**

Size is the easy half and, alone, worthless as evidence. Any response can be
made arbitrarily small by deleting the fields that carry meaning, and a
size-only check goes green either way. So every measurement below is paired
with a survival check, and the survival check is the one that matters.

## 1. Verdict

| Question | Answer |
| --- | --- |
| Is the briefing meaningfully smaller? | **Yes** — 40–60% against `detailed`, 57–70% against the T1 baseline |
| Did any integrity field disappear? | **No** — 0 lost, across 6 tools × 3 projects |
| Is what was dropped recoverable? | **Yes** — named in `truncation.dropped`, restored at `detail=diagnostic` |
| Do all three profiles differ? | **No** — `regular` is 4 characters from `economy`. See §5.1 |
| Are all read tools reduced? | **No** — 4 of 6 are byte-identical across profiles. See §5.2 |

The reservations are real and are recorded here rather than in a follow-up
target's discovery, but neither weakens the guarantee T5 exists to establish.

## 2. Method

Two instruments, because they fail differently.

**The harness** —
[`scripts/development/measure-mcp-responses.py`](../../scripts/development/measure-mcp-responses.py)
— measures live data at all three profiles and reports integrity-field
survival per tool. It shows what real projects actually produce, and it cannot
run in CI.

```bash
KAE_DATABASE_PROVIDER=postgresql \
KAE_DATABASE_URL=postgresql+psycopg://kae:...@localhost:5432/kae_memory \
  uv run python scripts/development/measure-mcp-responses.py
```

**The tests** —
[`tests/mcp_adapter/test_token_reduction.py`](../../tests/mcp_adapter/test_token_reduction.py),
22 of them — assert the same properties against a seeded project on every run.
A measurement records that the guarantee held once; a test is what keeps it
holding.

Both use character counts and the repository's `estimate_tokens` (`len // 4`),
which under-counts JSON. Absolute totals are indicative; **comparisons are
reliable**, because the same response measured two ways is measured
identically.

## 3. Measured — PostgreSQL `kae_memory`, 2026-08-05

`kae_get_project_briefing`, characters:

| Project | T1 baseline | `detailed` | `economy` | vs `detailed` | vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ministry Reporting | 12,199 | 9,125 | **3,631** | −60% | **−70%** |
| Local test | 14,108 | 8,571 | **5,252** | −39% | **−63%** |
| KAE-Memory | — | 8,394 | **5,073** | −40% | — |

`kae_get_readiness`, characters:

| Project | `detailed` | `economy` | Saved |
| --- | ---: | ---: | ---: |
| Ministry Reporting | 2,106 | 1,954 | −7% |
| Local test | 2,090 | 1,938 | −7% |
| KAE-Memory | 2,092 | 1,940 | −7% |

Readiness saves little because little was ever withheld from it: T4 moved only
the per-area `confirmed`/`proposed` counts to `diagnostic`. `state` and
`mandatory` stay at every level, because they answer the question readiness
exists to answer.

## 4. Nothing essential was lost

Per tool, on every project: integrity fields present at `detailed`, and how
many the `economy` response lost.

| Tool | Integrity fields | Lost at economy |
| --- | ---: | --- |
| `kae_list_projects` | 0 | — |
| `kae_get_project_briefing` | 2 | **none** |
| `kae_get_module_context` | 13 | **none** |
| `kae_search_knowledge` | 7 | **none** |
| `kae_get_open_decisions` | 1 | **none** |
| `kae_get_readiness` | 4 | **none** |

The check is computed by comparing two live responses, not by listing expected
field names, so a tool that grows a new integrity field is covered from the day
it is added rather than the day someone remembers to update a list.

**One field is withheld and does not count as lost.** At `economy` the briefing
drops `readiness.explanation` entire, and the per-area `state` inside it goes
with the section. That is a stated absence: `truncation.dropped` names the
section and `truncation.retrieve_with` says how to get it back. What the
integrity registry forbids is different and worse — a section that *stays* and
loses its integrity fields, because that response looks complete and is not.

Two specific losses were checked directly rather than by category, because they
are the ones that would do damage quietly:

- a search hit still declares its lifecycle at `economy`, so a proposed
  statement cannot be read as a confirmed one;
- search still reports `semantic_search_available: false`, so the hash-derived
  embedder does not become invisible under compaction.

## 5. What the measurement found that the target did not ask for

### 5.1 `regular` is not a third shape

| Profile | Briefing (KAE-Memory) |
| --- | ---: |
| `economy` | 5,073 |
| `regular` | 5,077 |
| `detailed` | 8,394 |

Four characters — the profile name echoed in `response_policy`. `REGULAR`'s
detail level is already `summary`, and the two differ only in prose level,
which changes nothing where no short form is registered.

This is not a defect. The default policy is the lean one, which is the correct
default for an agent-facing surface: a caller who asks for nothing gets the
compact response, and a caller who needs the arithmetic asks for `detailed`.
But three named profiles delivering two shapes is a thing the documentation
should say, and until now it did not.

### 5.2 Four of six read tools are not projected at all

`kae_list_projects`, `kae_get_module_context`, `kae_search_knowledge`, and
`kae_get_open_decisions` are byte-identical across all three profiles. They
have no entry in `TOOL_FIELD_LEVELS`, and a tool absent from that map is
returned whole.

Their reduction is real but comes from elsewhere: T4's pagination bounds three
of the four, and a page of 20 is what keeps a project with hundreds of
statements from arriving as one response. Detail levels are simply not the
mechanism doing the work there.

## 6. Defects found by the verification

T5 was written as a verification target. It found four things, which is the
argument for having written it at all.

**1. A compacted response was larger than the full one.** `kae_get_readiness`
at `economy` measured 2,271 characters against `detailed`'s 2,090. T4 taught
`_prune` to descend into list elements but appended one `dropped` entry per
element, so `truncation.dropped` listed `areas.confirmed` once for every area.
The reduction was paying for its own report of itself. Fixed by deduplicating:
a field withheld from every element of a list is one withheld field.

**2. Two field-map entries matched nothing.** `CLARIFICATION_FIELD_LEVELS`
named `questions[].knowledge_ids` and `questions[].newly_asked`. The pruner
builds dotted paths, so neither ever matched, and both fields shipped at every
detail level while the map said otherwise. Nothing failed; the compaction
simply was not there. Fixed to `questions.knowledge_ids` and
`questions.newly_asked`.

**3. A third entry was dead by precedence.** `ANSWER_FIELD_LEVELS` withheld
`next_steps` below `standard`, but `next_steps` is in the integrity registry
and the pruner honours the registry first. Removed rather than made to work:
what still has to happen before an answer becomes knowledge is exactly the kind
of statement the registry exists to protect.

**4. Nothing checked that a field map entry was reachable.** All three defects
above are the same defect — a map that claims a reduction the code does not
perform. There is now a test that resolves every path in every field map
against a real payload, so an entry that matches nothing fails rather than
silently doing nothing.

## 7. Caveats

- `kae_get_module_context` raises `CapabilityUnavailableError` on projects with
  no module scopes, which is the correct behaviour and not a measurement
  failure. Those rows are absent from the live sweep rather than zero.
- Writes are excluded. Measuring a write by performing one would leave evidence
  in whatever project was measured.
- The token figures are estimates. The reduction percentages are ratios of
  identical estimators and do not depend on the estimator being accurate.
