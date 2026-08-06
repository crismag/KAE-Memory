"""Writing a rendered package to the local filesystem (N30).

**The simplest contract proof, and explicitly not the permanent architecture.**
It exists so the publication path can be exercised end to end without an AWS
account, and so the provider interface is shaped by two implementations rather
than one.

Everything here is about one question: **can a caller make this write outside
the configured root?** The answer has to be no under every input, because the
root is the only thing standing between a publication request and the filesystem
of whatever runs KAE.

Three defences, and the third is the one that actually holds:

*The location comes from the target, not the request.* A request names a
`target_id`; the path prefix is registered configuration (N27). A caller that
could supply a path would not need to defeat any of this.

*Traversal and absolute paths are refused by inspection.* `../`, a leading `/`,
a drive letter, a null byte.

*The resolved path is checked against the resolved root.* After symlinks. This
is the defence that survives an input nobody anticipated, because it stops
asking what the string looks like and asks where the file would actually go.

**Not a browser download.** A hosted user choosing "download" is not
server-local publication; it needs its own delivery mechanism and this is not
it. The capability can be disabled entirely for hosted deployments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from kae_memory.application.render_service import RenderedPackage


class LocalPublicationError(RuntimeError):
    """The write was refused. Nothing was written."""


class OutsideRootError(LocalPublicationError):
    """The resolved destination is not beneath the configured root."""


@dataclass(frozen=True, slots=True)
class LocalWriteResult:
    """What was written, described so a person can find it."""

    root: str
    relative_path: str
    files_written: int
    bytes_written: int

    @property
    def reference(self) -> str:
        """The `external_reference` for a publication attempt.

        Relative to the root, deliberately. An absolute path in a durable record
        is a fact about one machine, and it will be read on another.
        """

        return self.relative_path


class LocalFilesystemProvider:
    """Write rendered artifacts beneath one configured root.

    The root is **runtime configuration**, never a request parameter, and the
    provider refuses to construct without one. A default of "the current
    directory" would be the kind of convenience that turns one bad request into
    files scattered through a repository.
    """

    provider = "local"

    def __init__(self, root: str | os.PathLike[str], enabled: bool = True) -> None:
        self._enabled = enabled
        self._root = Path(root).expanduser().resolve()

    @property
    def enabled(self) -> bool:
        """Whether this deployment permits local publication.

        Hosted deployments turn it off. A server writing files for a user who
        pressed a button in a browser is not publishing anywhere that user can
        reach, and doing it anyway fills a disk to no purpose.
        """

        return self._enabled

    def publish(
        self, package: RenderedPackage, relative_prefix: str, overwrite: bool = False
    ) -> LocalWriteResult:
        """Write every artifact beneath the root, or write nothing.

        **Verified first.** An unverified package is refused before a directory
        is created, because a partial write of content that did not match its
        record is worse than no write: it leaves files that look published.

        **Staged, then moved.** Each file is written to a temporary name in its
        final directory and renamed into place. A crash halfway through leaves
        the previous content, not half the new content — and a reader of a
        half-written document has no way to tell.
        """

        if not self._enabled:
            raise LocalPublicationError(
                "local publication is disabled in this deployment. This is a "
                "configuration decision, not a failure."
            )
        if not package.verified:
            raise LocalPublicationError(
                "the package did not match what the deliverable recorded, so "
                "nothing was written. Publishing it would leave files that look "
                "published and are not what they claim to be."
            )

        destination = self._resolve(relative_prefix)
        written = 0
        size = 0
        for artifact in package.artifacts:
            target = self._resolve(f"{relative_prefix}/{artifact.path}")
            if target.exists() and not overwrite:
                raise LocalPublicationError(
                    f"{target.relative_to(self._root)} already exists. Publishing "
                    f"over it would destroy content nobody asked to replace; pass "
                    f"overwrite to mean it."
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(f".{target.name}.staged")
            staged.write_bytes(artifact.content)
            staged.replace(target)
            written += 1
            size += artifact.size

        return LocalWriteResult(
            root=str(self._root),
            relative_path=str(destination.relative_to(self._root)),
            files_written=written,
            bytes_written=size,
        )

    def _resolve(self, relative: str) -> Path:
        """Resolve a location beneath the root, refusing anything that escapes.

        The order matters. Obvious attacks are refused by inspection so the
        error says what was wrong; everything else is caught by resolving the
        path and checking where it actually lands, which is the check that does
        not depend on having anticipated the input.
        """

        if not relative or not relative.strip():
            raise LocalPublicationError("a publication location cannot be empty")
        if "\x00" in relative:
            raise LocalPublicationError("a publication location cannot contain a null byte")

        candidate = PurePosixLike(relative)
        if candidate.is_absolute():
            raise OutsideRootError(
                f"{relative!r} is an absolute path. A target stores a location "
                f"beneath the configured root, never a place on the filesystem."
            )
        if ".." in candidate.parts:
            raise OutsideRootError(
                f"{relative!r} traverses upward. Nothing is written outside the "
                f"configured root under any input."
            )

        # After symlinks, and this is the defence that survives an input nobody
        # anticipated: it stops asking what the string looks like and asks where
        # the file would actually go.
        resolved = (self._root / relative).resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise OutsideRootError(
                f"{relative!r} resolves to {resolved}, which is outside the "
                f"configured root {self._root}. Nothing was written."
            )
        return resolved


def PurePosixLike(value: str) -> Path:
    """Interpret a location the way the platform will.

    Not `PurePosixPath`: on Windows, `C:\\evil` is absolute and a POSIX parser
    would call it a relative name with a colon in it. Using the platform's own
    rules means the check agrees with the filesystem that will act on it.
    """

    return Path(value)
