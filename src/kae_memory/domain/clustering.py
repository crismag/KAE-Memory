"""Complete-linkage clustering, generic over whatever is being clustered.

`D-100` built this for goals over cosine distance. `D-146` moved it here, because
`lexical.py` needs the same shape over a lexical distance and importing it from
`synthesizers.goals` would make every lexical consumer load all six synthesizers.

The body never touches an item except to hand it to the caller's own distance
function, so the type variable states what the behaviour already was.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import combinations


def cluster_by_complete_linkage[Item](
    items: Sequence[Item],
    distance: Callable[[Item, Item], float | None],
    *,
    radius: float,
) -> tuple[tuple[Item, ...], ...]:
    """Group items so that every pair inside a group is within ``radius``.

    Agglomerative, merging the closest admissible pair of clusters first, where
    a pair's score is the **largest** distance across them. That maximum is what
    makes this resist chaining: admitting a member that is close to one existing
    member but far from another would raise the score above the radius and the
    merge is refused.

    ``distance`` returns ``None`` where two items cannot be compared — an
    unembedded row, say. Unknown is not zero and not infinity: the pair simply
    never merges, so an unindexed item stays a cluster of one rather than
    joining the first thing it is asked about. A pair that *is* comparable and
    known to be far apart should say so with a large distance instead, so that
    ``None`` keeps meaning the one thing it means.

    Deterministic: ties break on the ordering of ``items``, so the same evidence
    produces the same clusters and the same identity keys.
    """

    groups: list[list[Item]] = [[item] for item in items]

    while True:
        best: tuple[float, int, int] | None = None
        for left, right in combinations(range(len(groups)), 2):
            worst = 0.0
            admissible = True
            for a in groups[left]:
                for b in groups[right]:
                    gap = distance(a, b)
                    if gap is None or gap > radius:
                        admissible = False
                        break
                    worst = max(worst, gap)
                if not admissible:
                    break
            if admissible and (best is None or worst < best[0]):
                best = (worst, left, right)
        if best is None:
            return tuple(tuple(group) for group in groups)
        _, left, right = best
        groups[left] = groups[left] + groups[right]
        del groups[right]


__all__ = ["cluster_by_complete_linkage"]
