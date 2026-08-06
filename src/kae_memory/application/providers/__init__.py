"""Publication providers: the things that actually write bytes somewhere.

Each one takes a **verified** `RenderedPackage` and a location resolved from a
registered target, and reports what it wrote. None of them decides where to
write, renders anything, or reads project knowledge — those boundaries are what
let a second provider be added without arguing with the first one's assumptions.

`local` is here (N30). `s3` (N31) and `github` (N32) are not: both need live
credentials to validate honestly, and an adapter that has never reached its
provider is not evidence that it can.
"""

from .local import (
    LocalFilesystemProvider,
    LocalPublicationError,
    LocalWriteResult,
    OutsideRootError,
)

__all__ = [
    "LocalFilesystemProvider",
    "LocalPublicationError",
    "LocalWriteResult",
    "OutsideRootError",
]
