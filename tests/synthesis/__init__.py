"""Golden corpora for knowledge synthesis (Phase 0).

Two datasets, because two ingestion paths fail differently.

`corpus.py` preserves the conversation-derived extraction as a repeatable
fixture. Its pathology is paraphrase: 47 goal-shaped sentences saying six
things.

`compute_lab.py` preserves the AWS Compute Lab **repository** ingest, the case
`17-KAE-MEMORY-EPISTEMIC-INGESTION-MODEL.md` names. Its pathology is repetition
and detail: hundreds of implementation facts restated across documents, and a
classifier that declines six of eight kinds by design.

For each, baseline tests characterise today's pathology and synthesis-gate
tests state the qualitative acceptance later phases must satisfy.
"""
