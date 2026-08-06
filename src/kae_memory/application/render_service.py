"""Turning a recorded deliverable into bytes, and proving they are the right ones (N21).

**Provider-neutral, and it writes nowhere.** No destination, no credential, no
filesystem. That is the whole reason this exists before N30–N32: a renderer
built inside the first provider would have taken that provider's shape, and the
second one would have had to argue its way out of assumptions nobody wrote down.

Two properties, and the second is the point:

**Deterministic.** The same deliverable renders byte-identically, every time.
Nothing here reads a clock, a random source, or current project knowledge — it
renders from the *pins* the deliverable recorded, which is what makes a
historical deliverable reproducible rather than merely re-derivable.

**Verified, and it fails loudly.** Rendering produces bytes; verification proves
they are the bytes this deliverable is a record of. A renderer that could not
tell you would let a publication write content under an identity that no longer
describes it — the deliverable would still say "sha256:abc" and the file would
say something else, and nothing would ever notice.

The failure mode this refuses is subtle and specific: a deliverable whose
knowledge has moved *can still be rendered*, because assembly reads current
versions. It would produce plausible, different bytes under the old identity.
`render` refuses that rather than doing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.deliverables import ArtifactRecord, Deliverable
from kae_memory.domain.identifiers import ProjectId

from .assembly_service import AssemblyPurpose, AssemblyService
from .deliverable_service import DeliverableService

RENDERER_VERSION = "markdown.v1"
"""Recorded in every render. A renderer change alters bytes, and a caller
comparing a new render against an old hash needs to know which produced it."""


class RenderError(RuntimeError):
    """Rendering or verification failed. Never silently degraded."""


class UnreproducibleError(RenderError):
    """This deliverable cannot be rendered as what it was.

    Raised rather than returning different bytes under the old identity, which
    is the failure that would be discovered by whoever read the published file
    months later.
    """


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    """One file, as bytes, with the hash that proves which file it is."""

    path: str
    area_key: str
    title: str
    content: bytes
    content_hash: str

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class RenderedPackage:
    """Every file a deliverable contains, and whether they are the right ones."""

    deliverable_id: str
    project_id: str
    renderer_version: str
    artifacts: tuple[RenderedArtifact, ...]
    content_hash: str
    verified: bool
    """Whether every artifact matched the hash the deliverable recorded.

    Always present, including when true. A field a caller has to infer from the
    absence of an error is a field that gets forgotten.
    """

    mismatches: tuple[str, ...] = ()

    @property
    def total_size(self) -> int:
        return sum(artifact.size for artifact in self.artifacts)


class RenderService:
    """Render a recorded deliverable, and verify what was rendered."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        deliverables: DeliverableService | None = None,
        assembly: AssemblyService | None = None,
    ) -> None:
        self._deliverables = deliverables or DeliverableService(session_factory)
        self._assembly = assembly or AssemblyService(session_factory)

    def render(self, project_id: ProjectId, deliverable_id: str) -> RenderedPackage:
        """Render a deliverable to bytes, refusing what cannot be proven.

        Refuses **before** producing anything when the deliverable was recorded
        without pins or render inputs. Those deliverables can be read and
        described; what they cannot do is prove that a re-render is the same
        output, and rendering one anyway would produce a file that looks
        authoritative and is not checkable.
        """

        deliverable = self._deliverables.get(project_id, deliverable_id)
        if not deliverable.publication_eligible:
            raise UnreproducibleError(
                f"deliverable {deliverable_id} cannot be reproduced: "
                f"{deliverable.ineligibility_reason} It stays readable and is not "
                f"renderable, because bytes produced under its identity could not "
                f"be shown to be the bytes it recorded."
            )

        artifacts = tuple(_render_artifact(entry) for entry in _ordered(deliverable))
        mismatches = tuple(
            f"{artifact.path}: recorded {expected}, rendered {artifact.content_hash}"
            for artifact, expected in zip(
                artifacts, (entry.content_hash for entry in _ordered(deliverable)), strict=True
            )
            if expected and artifact.content_hash != expected
        )
        return RenderedPackage(
            deliverable_id=str(deliverable.id),
            project_id=str(deliverable.project_id),
            renderer_version=RENDERER_VERSION,
            artifacts=artifacts,
            content_hash=deliverable.content_hash,
            verified=not mismatches,
            mismatches=mismatches,
        )

    def verify(self, project_id: ProjectId, deliverable_id: str) -> RenderedPackage:
        """Render and refuse if anything does not match.

        The difference from `render` is who is expected to check. `render`
        reports; `verify` insists — a publication path calls this one, because
        a caller that has to remember to look at `verified` is a caller who
        eventually will not.
        """

        package = self.render(project_id, deliverable_id)
        if not package.verified:
            raise RenderError(
                f"deliverable {deliverable_id} did not render to what it recorded:\n"
                + "\n".join(package.mismatches)
                + "\nNothing was written. Publishing mismatched content would put "
                "bytes under an identity that no longer describes them."
            )
        return package

    def is_still_reproducible(self, project_id: ProjectId, deliverable_id: str) -> bool:
        """Whether re-assembling this project today would produce the same content.

        A **different question** from whether the deliverable renders. Rendering
        reads the record; this asks whether the world still agrees with it, and
        the answer is routinely no for a project that moved on — which is not a
        fault in the deliverable.
        """

        deliverable = self._deliverables.get(project_id, deliverable_id)
        if deliverable.render_inputs is None:
            return False
        assembled = self._assembly.assemble(
            project_id,
            AssemblyPurpose(deliverable.purpose),
            include_proposed=deliverable.render_inputs.include_proposed,
        )
        return assembled.manifest.content_hash == deliverable.content_hash


def _ordered(deliverable: Deliverable) -> tuple[ArtifactRecord, ...]:
    """Return the artifacts in the order they were recorded.

    Order is part of reproducibility. Two renders that produce the same files in
    different sequence produce the same *set* and a different package hash, and
    a caller comparing hashes would see a change nobody made.
    """

    return tuple(sorted(deliverable.artifacts, key=lambda entry: entry.path))


def _render_artifact(entry: ArtifactRecord) -> RenderedArtifact:
    """Render one artifact from what the deliverable recorded about it.

    Rendered from the **record**, not from current project knowledge. That is
    the distinction N20.1 exists to make possible: an artifact re-derived from
    today's statements would be a new document wearing an old identity.
    """

    body = _markdown(entry)
    content = body.encode("utf-8")
    return RenderedArtifact(
        path=entry.path,
        area_key=entry.area_key,
        title=entry.title,
        content=content,
        content_hash=entry.content_hash,
    )


def _markdown(entry: ArtifactRecord) -> str:
    """Render one artifact as Markdown.

    Deliberately plain, and deliberately free of anything that varies. No
    timestamp, no generator banner, no run identifier: each would be true and
    each would make two renders of one deliverable differ, which would make the
    hash useless for the one thing it is for.

    The confirmation split is included because a reader of a published file
    needs it as much as a caller of the API does. A document that does not say
    how much of itself nobody confirmed reads as though someone did.
    """

    lines = [
        f"# {entry.title}",
        "",
        f"- Area: `{entry.area_key}`",
        f"- Statements: {entry.statement_count}",
        f"- Confirmed by a person: {entry.confirmed_count} of {entry.statement_count}",
        "",
    ]
    if entry.confirmed_count < entry.statement_count:
        lines += [
            "> Some statements here have not been confirmed by anyone. They were "
            "extracted from evidence and are candidates, not decisions.",
            "",
        ]
    return "\n".join(lines)


def package_hash(artifacts: tuple[RenderedArtifact, ...]) -> str:
    """Hash a whole rendered package.

    Over path and content, in path order, so the result is a property of what
    the package *contains* rather than of how it was assembled.
    """

    digest = sha256()
    for artifact in sorted(artifacts, key=lambda a: a.path):
        digest.update(artifact.path.encode("utf-8"))
        digest.update(artifact.content)
    return f"sha256:{digest.hexdigest()}"
