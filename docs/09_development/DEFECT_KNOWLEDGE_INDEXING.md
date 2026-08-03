# Defect — knowledge writes did not create searchable chunks

Status: **resolved**, 2026-08-03. Owning target: **M8 Semantic Retrieval**,
which was recorded complete while this was true.

## Problem

Knowledge committed to `knowledge_items` without any `knowledge_chunks`. Lexical
and vector search both read chunks, so every search returned an empty list for
knowledge that was present.

## Impact

A silent correctness failure rather than a missing optimisation. The empty
result is indistinguishable from "this project does not know that", so a caller
receives a confident wrong answer. Measured on the development database:

| Project | Knowledge items | Chunks |
| --- | ---: | ---: |
| KAE-Memory | 17 | **0** |
| Local test | 3 | **0** |
| Ministry Reporting | 12 | 10 |

Ministry Reporting had chunks only because `chunk_knowledge` was invoked by hand
while building retrieval fixtures. Every claim that "lexical search works" made
during 2026-08-02 was true of that one hand-prepared project and false of the
system.

## Root cause

`RetrievalService.chunk_knowledge` and `embed_pending` existed, were tested, and
were called by **nothing in `src/`**:

```
grep -rn "chunk_knowledge\|embed_pending" src/ scripts/   →   no results
```

Chunking was a capability with no caller. It was reachable only from tests and
from manual setup, which is precisely why the test suite passed.

## Why no existing target owned the fix

- **M8 Semantic Retrieval** owned this lifecycle and was recorded complete. Its
  carried caveat concerned ranking quality under a deterministic embedder, not
  chunks never being created.
- **T9/T10** own *re-embedding existing chunks*. Re-embedding cannot help when
  no chunks exist, so that target was insufficient by the decision rule.

No scheduled target owned chunk creation on write, so this was implemented
rather than deferred.

## Resolution

The hybrid lifecycle:

```
write or update knowledge
  → create or refresh lexical chunks in the same transaction
  → commit searchable lexical state
  → chunks land pending an embedding
  → embeddings generated separately, retryable
```

- `MemoryService.write_knowledge` indexes every item it writes, in the same
  transaction. There is no window in which knowledge exists unindexed.
- `MemoryService.correct_knowledge` refreshes chunks. Text is superseded in
  place where a chunk still exists at that index, so the stale vector keeps
  serving semantic hits until a re-embed lands (ADR-0008); surplus chunks are
  removed.
- `RetrievalService.chunk_knowledge` is idempotent, so backfills and retries are
  safe.
- `RetrievalService.indexing_status` reports items, chunks, and embedded chunks,
  which is what separates "no match" from "not indexed".
- `kae_search_knowledge` returns an `indexing` block, and warns explicitly when a
  project holds knowledge that no search can reach.
- `kae_get_module_context` reports `available: false` with
  `reason: project_knowledge_not_indexed` rather than an empty statement list.

Embedding is **not** synchronous. A provider outage degrades semantic search and
never blocks a knowledge write.

## Acceptance criteria

- [x] Production knowledge writes enter the indexing lifecycle automatically.
- [x] Lexical retrieval does not depend on manual setup.
- [x] Embeddings may be asynchronous and expose pending state.
- [x] Search distinguishes "no match" from "not indexed".
- [x] Existing unindexed projects can be safely backfilled.
- [x] Regression tests use normal write paths.

## Backfill

`scripts/development/backfill-knowledge-index.py`, using the product lifecycle
rather than a bespoke path.

| Project | Items | Chunks before | Chunks after | Embedded |
| --- | ---: | ---: | ---: | ---: |
| KAE-Memory | 17 | 0 | 17 | 17 |
| Ministry Reporting | 12 | 10 | 12 | 12 |
| Local test | 3 | 0 | 3 | 3 |

Verified through the live MCP tool: searching KAE-Memory for `memory` returns
two statements that were previously unreachable.

## Related, not fixed here

**`varchar` vs `uuid` on `knowledge_chunks.knowledge_id`.** Investigated and
**not a defect**: `knowledge_items.id` is `String(64)` from migration 0001, and
the chunk column matches it deliberately. Recorded in `tables.py` citing
ADR-0008 — "two identifier conventions in one table is the accepted cost of
leaving 0001 untouched". Diagnostic queries joining chunks to projects need an
explicit cast; the application does not, because it compares strings throughout.

**Module context remains unavailable.** This defect concerned the fallback
search only. Modules, module membership, traversal, and module-scoped readiness
still do not exist, and a term match still does not establish module membership.
