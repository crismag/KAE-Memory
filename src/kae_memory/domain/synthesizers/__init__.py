"""Domain synthesizers — evidence becomes a project model, per domain.

`ADR-0007`: extracted rows are evidence. A synthesizer is what turns them into
the small coherent thing a person reads, without destroying the rows it read.

Deliberately **not one generic summarizer** (doc 12). Goals cluster by outcome;
actors resolve into roles and responsibilities; unknowns reconcile against
current state. One prompt over all of them would produce prose that is not any
of those shapes.
"""

from .goals import (
    CLUSTER_RADIUS,
    GoalCandidate,
    GoalJudge,
    GoalJudgement,
    cluster_by_complete_linkage,
    is_conversation_local,
    medoid,
    plan_goal_model,
)

__all__ = [
    "CLUSTER_RADIUS",
    "GoalCandidate",
    "GoalJudge",
    "GoalJudgement",
    "cluster_by_complete_linkage",
    "is_conversation_local",
    "medoid",
    "plan_goal_model",
]
