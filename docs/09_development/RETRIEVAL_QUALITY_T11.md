# T11 — Semantic Retrieval Quality

Measured 2026-08-03 against the development corpus after the T10 migration to
Amazon Titan Text Embeddings V2 (embedding version 2, 32 chunks, 2 projects).

**Verdict: accepted with documented limitations.** Semantic retrieval is good
enough to rely on for the queries it is meant to answer, and the reason it is
acceptable is a distance cutoff that sits in a window 0.005 wide. That margin,
not the headline score, is the finding.

## Method

Twenty queries with expected answers written **before** the run
(`tests/retrieval/evaluation_set.py`), across five categories. Each records both
what makes an answer acceptable and what makes one unacceptable, because a
confident wrong answer is worse than silence and a hit rate alone cannot tell
them apart. Ground truth is written against knowledge that actually exists in
the corpus rather than synthetic fixtures — a paraphrase test on text we wrote
to match text we wrote proves nothing.

Every query was run through both retrieval paths. Reported by
`scripts/development/evaluate-retrieval.py`.

## Results

| category | n | semantic top-3 | lexical top-3 | semantic top-1 |
|---|---|---|---|---|
| exact terminology | 4 | 100% | 100% | 100% |
| paraphrase | 7 | 100% | 0% | 86% |
| cross-document | 3 | 100% | 33% | 67% |
| project isolation | 2 | 100% | 100% | 50% |
| weak / unrelated | 4 | 75% quiet | 100% quiet | — |

Overall semantic top-3 **100%**, MRR **0.91**. Overall lexical top-3 **44%**.

Latency: semantic median **98 ms**, max 291 ms. Lexical median **4 ms**, max
13 ms. The semantic figure includes a synchronous Titan call to embed the query;
it is a network round trip, not index time.

Paraphrase at 0% lexical against 100% semantic is the clearest result in the
set. Those seven queries share no vocabulary with their targets, and they are
the entire reason to pay for an embedding model.

## The change this required

`MAX_DISTANCE` was raised from **0.75 to 0.85**
([chunks.py](../../src/kae_memory/domain/chunks.py)).

The first run scored paraphrase at **43%**, with four queries returning nothing
at all. The cause was not ranking — it was the cutoff. Correct answers were
being retrieved and then discarded for sitting beyond 0.75. Measured
distances, relevant targets against unrelated queries:

| | best | worst |
|---|---|---|
| relevant top-1 | 0.649 | **0.840** |
| unrelated top-1 | **0.847** | 0.916 |

0.85 was chosen from that measurement rather than tuned until the symptom
disappeared, which was the explicit instruction for this target.

## Limitations

**The usable window for a global cutoff is 0.005 wide.** To admit the worst
genuine match (0.840) the threshold must be ≥ 0.841; to exclude the nearest
noise (0.847) it must be ≤ 0.846. Any single constant is fitted to a 20-query
set on 32 chunks and will not survive corpus growth. 0.85 was kept as a round
number rather than tuned to 0.845 precisely because 0.845 would claim a
resolution the evidence does not support.

**One weak query now leaks.** `"thanks, that's helpful"` returns one result at
distance 0.847 — conversational filler presented as a hit. This is the direct
cost of the threshold change and is the reason weak-query quiet fell from 100%
to 75%. It is recorded rather than patched: suppressing it needs a filler
classifier or lexical corroboration, both of which are features, not
corrections.

**Cross-document top-1 is 67%.** Synthesis queries have several contributing
statements and the ranking picks among them arbitrarily. Retrieval returns
parts, not an answer; nothing in the system yet composes them.

**The metadata prefix costs separation.** Chunks are embedded with a
project/kind/status prefix (ADR-0008). Measured against Titan, the prefix moves
relevant matches *further* away (+0.019) while pulling irrelevant ones *closer*
(−0.041). Separation between a relevant and an irrelevant statement was 0.130
with the prefix and 0.191 without — **47% wider without it.** Not changed here:
it would require a third full re-embed and belongs in its own target.

## Follow-ups

1. **Hybrid ranking** — combine semantic distance with lexical corroboration
   instead of thresholding on distance alone. This is the durable answer to the
   0.005 window; a better constant is not.
2. **Reconsider the embedding prefix** (ADR-0008), on the measurement above.
   Requires embedding version 3 and a corpus migration.
3. **Suppress conversational filler** before it reaches retrieval.
4. **Re-run this evaluation when the corpus grows materially.** The threshold is
   fitted to 32 chunks and is the first thing that will go stale.

## Regression protection

`tests/retrieval/test_retrieval_quality.py` — 8 tests locking the cutoff being
applied, silence on unrelated queries, project scoping, embedding-version
isolation, lexical remaining functional without vectors, and the 0.005-window
limitation itself, so an attempt to tighten the threshold fails there first and
reads why.

Vector geometry in those tests is chosen by the test rather than produced by a
model: asserting on Titan's distances would record one model's opinions on one
afternoon and break on any provider change for reasons unrelated to the
guarantee.
