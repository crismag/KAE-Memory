# ADR-0008 — Semantic embedding model and CockroachDB vector index

- **Status:** accepted
- **Date:** 2026-07-27
- **Closes:** OQ-014
- **Blocks:** M8 — Semantic Retrieval
- **Scope:** decision only. Implementation is M8 and does not begin here.
- **Amended by:** [`ADR-0011`](ADR-0011-test-against-cockroachdb.md). Correction 3
  below is **withdrawn**: the suite now runs on CockroachDB, so vector behaviour
  is verified like everything else and no test is skipped.

## Decision

Embeddings are generated through Amazon Bedrock using **Amazon Titan Text
Embeddings V2**, model identifier `amazon.titan-embed-text-v2:0`, configured for
**1,024 dimensions, normalised output, floating-point vectors**.

Vectors are stored in CockroachDB as fixed-dimension `VECTOR(1024)`. Similarity
is **cosine distance**, ranked with the cosine-distance operator and constrained
by project ownership before results are returned.

**One** vector index, on the embedding column of a shared knowledge-chunk table.
No per-type indexes for requirements, decisions, questions, messages, or
evidence — those stay metadata columns and filters on a common table.

### Why 1,024 rather than 512

The demonstration corpus is small, so the storage saving is not yet worth the
loss of semantic detail. KAE retrieves nuanced engineering knowledge — decisions,
requirements, constraints, open questions, evidence, architecture rationale —
where closely related language is common and finer distinctions matter.

At roughly 4 KB per embedding, even 10,000 chunks is about 40 MB of raw vector
values before index overhead. Acceptable for this release. Drop to 512 only if
retrieval evaluation later shows comparable quality.

## Four corrections against the repository as it stands

The proposal was written against an idealised schema. These are the differences
from what exists, resolved here so M8 does not discover them at implementation
time.

### 1. `knowledge_id` is `STRING(64)`, not `UUID`

Revision `0001` created `knowledge_items.id` as `STRING(64)`. A `UUID` foreign key
into it does not work — the same mismatch ADR-0005 resolved for
`knowledge_relationships`. `knowledge_chunks.knowledge_id` is therefore
`STRING(64)` referencing `knowledge_items(id)`, while `project_id` is `UUID`
referencing `projects(project_id)` and `chunk_id` is a `UUID` primary key.

Two identifier conventions in one table is ugly and is the accepted cost of
leaving revision `0001` untouched.

### 2. Identifiers and timestamps are application-generated

The proposal used `DEFAULT gen_random_uuid()` and `DEFAULT now()`. Every
identifier and timestamp in this codebase is generated in the application
(ADR-0005), and every repository sets both explicitly. `knowledge_chunks`
follows that convention rather than introducing a second one — a mixed model
makes it unclear which layer owns a value, and the clock in particular is
injected so tests can control it.

### 3. `VECTOR` cannot be exercised on SQLite — the test strategy changes ~~(withdrawn)~~

Every test today runs on SQLite, and `tests/conftest.py` builds the schema with
`Base.metadata.create_all`. SQLite has no `VECTOR` type, no cosine operator, and
no vector index. Adding a `VECTOR` column to the shared metadata would break the
entire existing suite at fixture setup.

Therefore:

- the vector column and index are **CockroachDB-only** and must not be part of
  the metadata SQLite builds;
- M8 tests split in two. **Portable tests** — chunking boundaries, metadata
  prefixes, content hashing, embedding lifecycle and staleness, provenance,
  filters — run on SQLite as now. **Vector tests** — the cosine query, the index,
  and the evaluation fixture — require a CockroachDB cluster and are skipped, not
  silently passed, when one is absent;
- CI must report vector tests as skipped rather than green. A suite that appears
  to pass while never executing a vector query is worse than one that admits the
  gap.

~~This is the first capability the project cannot fully verify on the portable
test path, and it is recorded as such.~~

**Withdrawn by ADR-0011.** Rather than accept an unverifiable capability, the
suite moved to CockroachDB. Vector columns, the cosine operator, and the index
are exercised in the ordinary run, and the evaluation fixture is a normal test.

### 4. Titan is not an Anthropic model — a second client is required

`amazon.titan-embed-text-v2:0` is an Amazon model. The Anthropic SDK's Bedrock
client cannot invoke it; it needs `boto3` against `bedrock-runtime`.

So M8 adds a **separate `EmbeddingPort`** — not a method on `ExtractionPort` —
with its own adapters and its own optional dependency. Extraction and embedding
share a provider platform, not a client.

The determinism rule from ADR-0006 carries over unchanged: a deterministic
embedding adapter backs the tests, and **no test may make a live embedding call.**

## Chunk representation

Embeddings attach to durable knowledge chunks, never directly to projects,
sessions, or whole documents.

```text
knowledge_item
  └── knowledge_chunk
        └── embedding VECTOR(1024)
```

| Field | Notes |
| --- | --- |
| `chunk_id` | `UUID`, application-generated primary key |
| `project_id` | `UUID` → `projects` |
| `knowledge_id` | `STRING(64)` → `knowledge_items(id)` — see correction 1 |
| `knowledge_type` | metadata filter, not a separate index |
| `chunk_index` | sequence within the parent |
| `chunk_text` | the text actually embedded, prefix included |
| `embedding` | `VECTOR(1024)`, CockroachDB only |
| `embedding_model` | e.g. `amazon.titan-embed-text-v2:0` |
| `embedding_dimensions` | `1024` |
| `embedding_version` | schema version of the embedding space |
| `content_hash` | staleness detection |
| `embedded_at` | nullable until embedded |
| `created_at` | application-set |

`UNIQUE (knowledge_id, chunk_index, embedding_version)`.

**Model metadata is stored even though one model is approved.** Vectors from
different models are not comparable in one search space, so re-embedding must be
auditable and safe. Recording the model does not make this a multi-model
architecture — it makes the single-model assumption checkable.

### Chunking

- Embed semantic sections, not whole projects.
- Target 300–700 tokens; do not normally exceed ~1,000. Titan V2 accepts 8,192,
  so the ceiling is a retrieval-quality choice, not a model limit.
- A short requirement, decision, or open question stays **one** chunk.
- Long transcripts, documents, and summaries split on semantic boundaries, not
  fixed character counts.
- Preserve headings and entity identifiers.
- Include a short metadata prefix (project, type, title, status) where it
  materially improves meaning:

```text
Type: Architecture Decision
Project: KAE Memory
Title: Durable worker runtime
Status: Approved

A dedicated worker claims AgentRun records using renewable CockroachDB
leases and fencing tokens...
```

## Embedding lifecycle

A chunk needs embedding when it is new, its text changes, its content hash no
longer matches, or the approved embedding version changes.

Generation runs **asynchronously through the durable worker runtime** (ADR-0007),
which means it inherits fencing, bounded retry, and checkpointing rather than
reimplementing them.

**Knowledge persistence does not depend on successful embedding.** A knowledge
item and its chunks may exist with a pending or failed embedding state and be
retried without recreating the authoritative item. Memory is the product;
retrieval is an index over it.

Changing the model, dimensions, or embedding-space semantics requires a new
embedding version and re-embedding of all participating chunks. Vectors from
different versions must never be compared in one query or index.

## Retrieval

1. validate project access;
2. embed the query with the approved model, 1,024 dimensions, normalised;
3. search the vector index by cosine distance;
4. constrain by project and any requested knowledge type;
5. return the top chunks with provenance and distance.

Default limit: **8 chunks**. Results carry chunk text, knowledge item identifier,
type, title, source reference, cosine distance, and project.

**Not in the first implementation:** a second embedding model, multiple vector
indexes, an external vector database, cross-encoder reranking, multimodal
embeddings, or automatic model fallback. Each is an incremental improvement after
the first retrieval proof, not part of it.

## Validation — the part that makes this real

M8 must include a **fixed evaluation set of 15–25 representative queries with
expected relevant knowledge items**, for example:

```text
Query: "How does KAE recover after its worker dies?"
Expected: AR-03 worker runtime decision; AT-009 recovery acceptance test;
          AgentRun lease design
```

Acceptance requires the expected item to appear within the approved top-k.

**Creating embeddings and an index is not evidence that retrieval works.** A
vector index will happily return the eight least-wrong answers to a query it
fundamentally cannot serve. Without the evaluation fixture, this decision would
be implemented but unvalidated, and FR-013's "explanation of why a result was
included" would be decoration.

## Requirements

- CockroachDB **v25.4 or later** — vector indexes reached general availability
  there, with distributed scaling, online backfill, incremental maintenance, and
  cosine, L2, and inner-product distance. The cluster version is a deployment
  precondition for M8, not an implementation detail.
- Bedrock access to `amazon.titan-embed-text-v2:0` in the deployment region.

## Consequences

**Positive.** CockroachDB remains the single operational and vector store — no
second database to run, back up, or keep consistent. One fixed 1,024-dimensional
space is easy to reason about. Knowledge types are searched together while
retaining metadata filters. Embedding failure never blocks authoritative
persistence. Retrieval quality becomes testable rather than assumed.

**Negative.** Model replacement requires versioning and full re-embedding. A
second provider client and dependency arrive. The chunk table carries two
identifier conventions. The suite depends on a running CockroachDB (ADR-0011).

**Accepted risk.** Titan V2's retrieval quality on this specific domain is
unmeasured, which is exactly what the evaluation fixture exists to expose — early,
and against a fixed set, rather than during the demonstration.

## Related

- [`ADR-0005-m5-physical-schema.md`](ADR-0005-m5-physical-schema.md) — identifier conventions and the `STRING(64)` constraint
- [`ADR-0006-extraction-contract.md`](ADR-0006-extraction-contract.md) — the port pattern and the no-live-calls rule
- [`ADR-0007-worker-runtime-and-leases.md`](ADR-0007-worker-runtime-and-leases.md) — the runtime embedding generation uses
- [`../RETRIEVAL_ARCHITECTURE.md`](../RETRIEVAL_ARCHITECTURE.md)
