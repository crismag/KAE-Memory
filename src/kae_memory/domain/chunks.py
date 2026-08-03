"""Knowledge chunks — the unit that gets embedded.

Embeddings attach to chunks, never to whole entities (ADR-0008). A short
requirement stays one chunk; a long transcript splits on semantic boundaries.

A chunk records which model embedded it, at which dimensions, under which
embedding version, and the hash of the text that was embedded. Vectors from
different models are not comparable in one search space, so re-embedding has to
be auditable — recording the model is what makes the single-model assumption
checkable rather than assumed.
"""

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import ChunkId, KnowledgeItemId, ProjectId
from .models import KnowledgeKind

EMBEDDING_VERSION = 2
"""The current embedding space.

Changing the model, its dimensions, or the prefix convention means a new version
and a full re-embed — never a silent mix of old and new vectors.

Version 1 was the hash-derived deterministic adapter. Version 2 is Titan Text
Embeddings V2. Bumped 2026-08-03: without it, Titan vectors would have been
written at version 1 and ranked against hash-derived ones in the same cosine
query, which returns confident nonsense rather than failing. Version-1 chunks
are excluded from semantic search until re-embedded, so retrieval degrades to
lexical rather than becoming quietly wrong.
"""

MAX_DISTANCE = 0.85
"""How far a vector may sit from the query and still count as a result.

Raised from 0.75 to 0.85 on 2026-08-03, from measurement rather than by feel.
Against Titan V2 on this corpus, relevant paraphrase matches land between 0.72
and 0.842 while unrelated queries start at 0.855 — 0.75 was cutting off genuine
answers, which is why five paraphrase queries returned nothing at all.

The margin is **0.013**, and that is thin. It is fitted to a twenty-query
evaluation on thirty-two chunks, so it will need re-tuning as the corpus grows;
hybrid ranking is the durable answer rather than a better constant.

Cosine distance over unit vectors runs 0 to 2, with 1.0 meaning orthogonal —
no relationship at all. A cutoff below 1.0 is therefore the line between "this
is about your query" and "this is merely the closest row we happened to store".

Provisional, and it should be tuned against the evaluation fixture once a real
embedding model is in place. Its job today is structural: without any cutoff,
nearest-neighbour search on a small corpus returns the whole corpus for every
query, which reads as a ranking failure but is really a missing filter.
"""

TARGET_TOKENS = 500
"""Middle of the 300 to 700 token band in ADR-0008."""

MAX_TOKENS = 1000
"""Soft ceiling. Titan V2 accepts 8,192, so this is a retrieval-quality choice
rather than a model limit: a chunk covering too much dilutes its own embedding.
"""

_CHARS_PER_TOKEN = 4
"""Rough English estimate, used only to decide where to split.

Deliberately not a tokenizer call: splitting must be deterministic and offline,
and being slightly wrong about a boundary costs far less than a network round
trip per chunk.
"""

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class EmbeddingState(StrEnum):
    """Where a chunk is in its embedding lifecycle."""

    PENDING = "pending"
    EMBEDDED = "embedded"
    STALE = "stale"
    FAILED = "failed"
    CLAIMED = "claimed"
    """Held by a migration runner that has not yet written a result.

    A claim, not a lifecycle state. It exists because embedding is an external
    call and the application never holds a transaction open across one, so two
    runners cannot be separated by a row lock. Claiming is a compare-and-set:
    exactly one runner wins.

    A crashed runner leaves chunks claimed. They are deliberately *not* eligible
    for ordinary selection — a second runner picking them up is the race this
    prevents — so recovery is explicit, via ``release_claims``.
    """


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text``."""

    return max(1, len(text) // _CHARS_PER_TOKEN)


def content_hash(text: str) -> str:
    """Return the hash used to detect that embedded text has changed."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """One embeddable span of a knowledge item."""

    id: ChunkId
    project_id: ProjectId
    knowledge_id: KnowledgeItemId
    knowledge_kind: KnowledgeKind
    chunk_index: int
    text: str
    created_at: datetime
    embedding_version: int = EMBEDDING_VERSION
    state: EmbeddingState = EmbeddingState.PENDING
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedded_at: datetime | None = None
    hash_value: str = ""

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise DomainInvariantError("chunk index must not be negative")
        if not self.text.strip():
            raise DomainInvariantError("chunk text must not be empty")
        if self.created_at.tzinfo is None:
            raise DomainInvariantError("chunk created_at must be timezone-aware")
        if self.embedded_at is not None and self.embedded_at.tzinfo is None:
            raise DomainInvariantError("chunk embedded_at must be timezone-aware")
        if self.embedding_version < 1:
            raise DomainInvariantError("embedding version must be positive")
        if not self.hash_value:
            object.__setattr__(self, "hash_value", content_hash(self.text))

    @property
    def needs_embedding(self) -> bool:
        """Return whether this chunk should be sent to the embedder.

        A failed chunk is included: failure is retried, and an unembedded chunk
        only costs recall, never correctness — knowledge persistence never
        depends on embedding succeeding.
        """

        return self.state in {EmbeddingState.PENDING, EmbeddingState.STALE, EmbeddingState.FAILED}

    def is_stale_against(self, text: str, embedding_version: int = EMBEDDING_VERSION) -> bool:
        """Return whether stored text or the embedding space has moved on."""

        return content_hash(text) != self.hash_value or embedding_version != self.embedding_version

    def embedded(self, model: str, dimensions: int, moment: datetime) -> "KnowledgeChunk":
        """Return this chunk marked embedded by ``model``."""

        return replace(
            self,
            state=EmbeddingState.EMBEDDED,
            embedding_model=model,
            embedding_dimensions=dimensions,
            embedded_at=moment,
        )

    def failed(self) -> "KnowledgeChunk":
        """Return this chunk marked as having failed to embed."""

        return replace(self, state=EmbeddingState.FAILED)

    def superseded_by(self, text: str) -> "KnowledgeChunk":
        """Return this chunk carrying new text and marked stale.

        The old vector stays in place until the new one is written, so retrieval
        degrades rather than disappearing while a re-embed is pending.
        """

        return replace(self, text=text, hash_value=content_hash(text), state=EmbeddingState.STALE)


def metadata_prefix(
    project_name: str, kind: KnowledgeKind, title: str | None = None, status: str | None = None
) -> str:
    """Return the short prefix prepended to embedded text.

    Gives the model the context a bare sentence lacks — that "monthly" is a rule
    in a reporting project rather than a stray adverb — without maintaining a
    separate index per knowledge type.
    """

    lines = [f"Type: {kind.value}", f"Project: {project_name}"]
    if title:
        lines.append(f"Title: {title}")
    if status:
        lines.append(f"Status: {status}")
    return "\n".join(lines)


def strip_metadata_prefix(text: str) -> str:
    """Return the chunk body without the prefix :func:`metadata_prefix` added.

    The prefix helps an embedding model and hurts a lexical one: every chunk in
    a project literally contains the word "project", so matching against the
    stored text would rank the whole corpus for a one-word query. Lexical
    matching runs on the body; kind and status stay available as real filters.
    """

    head, separator, body = text.partition("\n\n")
    if not separator:
        return text
    lines = head.splitlines()
    return body if lines and lines[0].startswith("Type: ") else text


def split_text(
    text: str, target_tokens: int = TARGET_TOKENS, max_tokens: int = MAX_TOKENS
) -> list[str]:
    """Split ``text`` on semantic boundaries, not fixed character counts.

    Short input returns unchanged — a requirement or decision is one thought and
    splitting it would produce two chunks that each mean less than the whole.
    Longer input splits on paragraphs first, then sentences, so a chunk boundary
    falls where the meaning already breaks.
    """

    if estimate_tokens(text) <= max_tokens:
        return [text.strip()] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for block in _semantic_blocks(text):
        block_tokens = estimate_tokens(block)
        if current and current_tokens + block_tokens > target_tokens:
            chunks.append("\n\n".join(current).strip())
            current, current_tokens = [], 0
        current.append(block)
        current_tokens += block_tokens

    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _semantic_blocks(text: str) -> list[str]:
    """Return paragraphs, splitting any that alone exceed the ceiling."""

    blocks: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        stripped = paragraph.strip()
        if not stripped:
            continue
        if estimate_tokens(stripped) <= MAX_TOKENS:
            blocks.append(stripped)
            continue
        blocks.extend(_split_sentences(stripped))
    return blocks


def _split_sentences(paragraph: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in _SENTENCE.split(paragraph):
        sentence_tokens = estimate_tokens(sentence)
        if current and current_tokens + sentence_tokens > TARGET_TOKENS:
            parts.append(" ".join(current))
            current, current_tokens = [], 0
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        parts.append(" ".join(current))
    return parts
