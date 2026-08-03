# Phase B — Real Semantic Retrieval: completion report

Completed 2026-08-03. Targets T6–T11.

Phase B set out to replace a placeholder with a real embedding model without
ever letting search return confident nonsense in the process. It did that, and
it ends with retrieval that answers paraphrased questions — the capability the
system did not have before — plus one honest limitation that is documented
rather than smoothed over.

## What changed

**T6 / T7 — provider selection and provenance.** Every chunk now records
`embedding_model`, `embedding_dimensions`, and `embedding_version`. Without
these a corpus cannot say which space its vectors belong to, and a migration
cannot know what is left to do.

**T8 — the real provider.** `agents/provider.py` selects an embedder from
`KAE_EMBEDDING` and raises when misconfigured rather than silently falling back
to hash-derived vectors. Region resolves through `AWS_REGION`,
`AWS_DEFAULT_REGION`, then the active profile.

The refusal to fall back is the design decision worth keeping. A fallback would
have produced a system that always appears to work; the failure mode it hides is
a search that returns plausible rankings computed from nothing.

**T9 — restartable migration.** `ReembeddingService` plus
`scripts/development/reembed-knowledge.py`. `EMBEDDING_VERSION` bumped to 2 and
selection made version-aware, so Titan vectors are never ranked against
hash-derived ones in the same cosine query. Claiming is compare-and-set, so two
runners divide work rather than duplicating it; the provider is called before
anything is overwritten, so a failed request leaves the previous vector intact.

**T10 — corpus migrated.** All 32 chunks across both projects moved to Titan V2.
Twelve post-migration checks passed, a rerun was a no-op, and lexical retrieval
stayed functional throughout — the migration was never a window of blindness.

**T11 — quality measured.** Twenty queries with ground truth written before the
run. Semantic top-3 100%, MRR 0.91, **paraphrase 100% against lexical 0%**.
Details and limitations in [RETRIEVAL_QUALITY_T11.md](RETRIEVAL_QUALITY_T11.md).

## What Phase B did not settle

**A single global distance threshold cannot separate signal from noise on this
corpus.** The window is 0.005 wide. `MAX_DISTANCE = 0.85` is inside it and was
set from measurement, but it is fitted to 32 chunks and will go stale.
Hybrid ranking is the follow-up; another constant is not.

One weak query now returns a result it should not. Cross-document top-1 is 67%
because retrieval returns parts and nothing composes them. The ADR-0008 metadata
prefix measurably costs separation (0.130 with, 0.191 without) and revisiting it
needs a third re-embed.

## Errors made during this phase

Recorded because the checklist is a control register and a clean one would be
misleading.

- I mixed embedding spaces in my own diagnostic scripts — omitting
  `KAE_EMBEDDING=titan` meant hash-derived query vectors were compared against
  Titan document vectors, producing confident numbers (0.947, 0.970) that meant
  nothing. I chased that discrepancy for several rounds before finding the
  cause. It is a live demonstration of exactly the failure `EMBEDDING_VERSION`
  exists to prevent, in the one place versioning cannot reach: ad-hoc scripts.
- My first instinct on the 43% paraphrase result was that ranking was broken.
  It was the cutoff discarding correct answers. Measuring the distances before
  changing anything was the instruction, and it was the right one.

## Verification

Full suite green. `tests/retrieval/test_retrieval_quality.py` adds 8 tests
locking the Phase B guarantees, including one that asserts the 0.005-window
limitation so a later threshold tightening fails there first and reads why.

## Next

Phase C — knowledge review surfaces (T12–T15): `kae_confirm_knowledge`,
`kae_reject_knowledge`, `kae_correct_knowledge`, and audit-trail verification.
