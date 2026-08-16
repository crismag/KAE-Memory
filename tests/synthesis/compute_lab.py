"""Repository-derived extraction corpus: the AWS Compute Lab regression case.

`17-KAE-MEMORY-EPISTEMIC-INGESTION-MODEL.md` names **AWS Compute Lab** as the
case this architecture must be measured against. KAE consumed an existing
repository to learn a project, and the Review experience reported the result as
work for the human. The document's own sentence is the acceptance criterion:

> A consumed project must become knowledge, not a work task for the user.

## What the live database says

Verified against the development instance on 2026-08-15, project
``dabbcd54-4bd2-4ebb-abec-ec15df131995``:

- 809 knowledge items — 803 ``proposed``, 6 ``validated``;
- 692 of them have no row in ``knowledge_area_links`` — "unclassified";
- 103 of them are ``unknown`` — the open questions the screenshot counted;
- extraction ran as 66 succeeded and 35 abandoned ``requirements`` runs, so
  the backlog is what *survived* F-018's loss, not what the repository said;
- the only areas with any assignment are ``users_and_stakeholders`` (62) and
  ``constraints_and_assumptions`` (55).

Those last two are not a coincidence and not a classifier having a bad day.
``review_service.classify_offline`` assigns only the kinds that exactly one
area accepts, which `readiness.SOFTWARE_TEMPLATE` documents as ``ACTOR`` and
``ASSUMPTION`` alone. Every ``goal``, ``requirement``, ``rule``, ``constraint``
and ``decision`` is therefore left for a person by construction. The 692 is a
deployment running without a review model, presented to the user as a filing
job. That is `EPI-3`.

## What this fixture is

180 observations in the *shape* of those 809 — not a copy of them. Kind
proportions are held within a point of the live distribution, so the
unclassified fraction this fixture produces (154 of 180, 85.6%) reproduces the
live one (692 of 809, 85.5%) through the real ``classify_offline`` path rather
than by assertion.

Content is written in the register of the live rows, which is worth stating
because repository-derived observations do not read like conversation-derived
ones. `corpus.py` holds sentences a person said about a product. These are
sentences a *document* asserted about an implementation: imperative, specific,
full of file paths, CLI flags and queue semantics, and frequently the same fact
restated by five chunks of five different markdown files. The conversation
corpus's pathology is paraphrase; this one's is repetition plus detail.

The named cases below are doc 17's own list. Exact synthesized cardinality is
not an acceptance number — `17` says so explicitly ("Exact counts are not
acceptance criteria").
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from kae_memory.domain.models import KnowledgeKind

# --- Named regression cases -------------------------------------------------
#
# Doc 17's failure patterns, each a tag on the observations that carry it.
# Synthesis must handle each; how many objects it produces is not prescribed.

REPEATED_IMPLEMENTATION: Final = "repeated-implementation"
"""Outcome 4. The same implementation fact restated by many chunks."""

IMPLEMENTATION_DETAIL: Final = "implementation-detail"
"""Doc 17's `Is it merely implementation detail?` — a flag default is not
project knowledge, however true it is."""

CHUNK_LOCAL_QUESTION: Final = "chunk-local-question"
"""Outcome 8. A question one chunk could not answer that the corpus answers."""

MECHANICALLY_CLASSIFIABLE: Final = "mechanically-classifiable"
"""Outcome 3. Statements whose area is plain from the statement itself, and
which are unclassified today only because their kind maps to several areas."""

HARNESS_NOISE: Final = "harness-noise"
"""Outcome 5. Material about the agent harness that wrote the documents, not
about AWS Compute Lab. Real: the live corpus carries ~110 such rows."""

TRUNCATION_ARTIFACT: Final = "truncation-artifact"
"""Pipeline residue promoted to a durable unknown — the extractor reporting
that its own input was cut off."""

OBSERVED_FACT: Final = "observed-fact"
"""Doc 17's `docker-compose declares PostgreSQL` case. The repository is
sufficient evidence; asking a person to confirm it is the defect."""

PROFILE_CONFLICT: Final = "profile-conflict"
"""Outcome 9. A genuine contradiction between two repository statements."""

DEFERRED_DECISION: Final = "deferred-decision"
"""Outcomes 9-11. The one thing here that really does need the project owner."""

CONFIRMATION_ABANDONED: Final = "confirmation-abandoned"
"""The two rows a person confirmed before stopping. Live: 6 of 809."""

# Merge clusters inside REPEATED_IMPLEMENTATION, named so a gate can point at
# one rather than at the whole tag.
AWS_PROFILE: Final = "aws-profile"
DEAD_LETTER_QUEUE: Final = "dead-letter-queue"
IDEMPOTENT_CONSUMER: Final = "idempotent-consumer"
VISIBILITY_TIMEOUT: Final = "visibility-timeout"
LEAST_PRIVILEGE_IAM: Final = "least-privilege-iam"
SERVICE_DECOUPLING: Final = "service-decoupling"

# --- Statements a gate names directly ---------------------------------------

PROJECT_IDENTITY_TEXT: Final = (
    "Demonstrate practical orchestration engineering capabilities through an SQS "
    "subsystem as a technical portfolio showcase."
)

ADMIN_PROFILE_DECISION_TEXT: Final = (
    "The two CLIs are separated by privilege level: aws-sqs-client runs under the "
    "aws-compute-lab profile and aws-sqs-admin under aws-compute-lab-admin."
)
ADMIN_PROFILE_RULE_TEXT: Final = (
    "The AWS profile aws-compute-lab must be exported before running SQS admin commands."
)

SAFE_DELETE_QUESTION_TEXT: Final = (
    "What constitutes 'safe' for message deletion — is it defined by task "
    "completion, result publication, or some other condition?"
)
SAFE_DELETE_ANSWER_TEXT: Final = (
    "The poll loop must follow the sequence: receive message, validate payload, "
    "track local receipt, execute task, upload result, publish completion, delete message."
)

DEFERRED_LAYER_TEXT: Final = (
    "Which abstraction layer the MVP targets is explicitly deferred by the author "
    "and blocks full scoping of the implementation."
)

HEADLINE_COUNTS: Final[Mapping[str, int]] = {
    KnowledgeKind.REQUIREMENT.value: 54,
    KnowledgeKind.RULE.value: 44,
    KnowledgeKind.UNKNOWN.value: 23,
    KnowledgeKind.GOAL.value: 15,
    KnowledgeKind.ACTOR.value: 14,
    KnowledgeKind.ASSUMPTION.value: 12,
    KnowledgeKind.CONSTRAINT.value: 10,
    KnowledgeKind.DECISION.value: 8,
}
"""Kind proportions scaled from the live 809 to 180. Held within one point of
the live distribution so the unclassified fraction is reproduced, not asserted."""

ATTENTION_BOUND: Final = 5
"""Doc 17's Studio story is *"3 matters need your judgment."* Not a target."""

LIVE_ITEM_COUNT: Final = 809
LIVE_UNCLASSIFIED_COUNT: Final = 692
LIVE_UNKNOWN_COUNT: Final = 103
LIVE_VALIDATED_COUNT: Final = 6
"""The numbers doc 17 quotes, kept beside the fixture that stands in for them."""


@dataclass(frozen=True, slots=True)
class ExtractedObservation:
    """One extracted row as repository ingestion stores it today."""

    kind: KnowledgeKind
    content: str
    source: str
    cases: frozenset[str]
    confirm: bool = False


def _obs(
    kind: KnowledgeKind,
    content: str,
    *cases: str,
    source: str | None = None,
    confirm: bool = False,
) -> ExtractedObservation:
    tag = source or f"repository:aws-compute-lab:{kind.value}:{content[:24]}"
    return ExtractedObservation(kind, content, tag, frozenset(cases), confirm)


_GOALS: tuple[ExtractedObservation, ...] = (
    _obs(KnowledgeKind.GOAL, PROJECT_IDENTITY_TEXT),
    _obs(
        KnowledgeKind.GOAL,
        "Enable distributed simulation execution for parameter sweeps, scientific "
        "workloads, and engineering studies.",
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Connect a local developer machine to cloud workers without exposing inbound "
        "ports or building custom network tunnels.",
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Give every job a durable handoff point so work descriptions and status are "
        "not lost in transit.",
        REPEATED_IMPLEMENTATION,
        SERVICE_DECOUPLING,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Give each part of the system breathing room so the API, worker, and dashboard "
        "are decoupled from one another.",
        REPEATED_IMPLEMENTATION,
        SERVICE_DECOUPLING,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Demonstrate how queues become infrastructure for coordinating work across "
        "services that should not be tightly coupled.",
        REPEATED_IMPLEMENTATION,
        SERVICE_DECOUPLING,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "The separation of services makes the system easier to scale and easier to debug.",
        REPEATED_IMPLEMENTATION,
        SERVICE_DECOUPLING,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Each layer has a narrow responsibility so operational behavior is easy to "
        "reason about and test.",
        REPEATED_IMPLEMENTATION,
        SERVICE_DECOUPLING,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Keep AWS credentials out of the browser while the UI still shows job lists, "
        "artifacts, workers, and dashboard summaries.",
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Use EC2 workers when jobs need more runtime, CPU, memory, disk, or custom "
        "packages than a short-lived function can provide.",
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Maintain a small set of admin scripts to learn and test IAM workflows without "
        "turning the repository into a platform framework.",
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Describe current repository behavior and the operator-facing model in the docs/ tree.",
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Design the compute_lab_mvp web application AWS interface in the current design "
        "phase 2 context.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Design a compute_lab_mvp web application AWS interface, continuing from a "
        "previous design phase 2.",
        HARNESS_NOISE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.GOAL,
        "Present a single user-readable specialist timeline despite internally separate "
        "truth layers.",
        HARNESS_NOISE,
    ),
)

_ACTORS: tuple[ExtractedObservation, ...] = (
    _obs(KnowledgeKind.ACTOR, "Customer (web console user)"),
    _obs(
        KnowledgeKind.ACTOR,
        "Admin user responsible for IAM workflows, destructive SQS operations, and "
        "deployment using the aws-compute-lab-admin profile.",
        AWS_PROFILE,
    ),
    _obs(
        KnowledgeKind.ACTOR,
        "Admin workstation or pipeline — deploys provisioning scripts and admin tools "
        "using a privileged AWS role.",
        LEAST_PRIVILEGE_IAM,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.ACTOR,
        "Worker runtime (compute_lab_mvp/workers/local/)",
        OBSERVED_FACT,
    ),
    _obs(KnowledgeKind.ACTOR, "API Lambdas (compute_lab_mvp/lambda/handlers/)", OBSERVED_FACT),
    _obs(KnowledgeKind.ACTOR, "Local web console (compute_lab_mvp/web/)", OBSERVED_FACT),
    _obs(
        KnowledgeKind.ACTOR,
        "Shared libraries (lib/python/, compute_lab_mvp/shared/)",
        OBSERVED_FACT,
        IMPLEMENTATION_DETAIL,
    ),
    _obs(KnowledgeKind.ACTOR, "aws-sqs-client CLI: handles runtime-safe message operations"),
    _obs(KnowledgeKind.ACTOR, "aws-sqs-admin CLI: handles privileged queue administration"),
    _obs(
        KnowledgeKind.ACTOR,
        "A local or EC2 worker consumes the queue, updates status, and writes outputs",
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.ACTOR,
        "Orchestrator Service sits between the SQS Request Queue and the Worker Queue",
        REPEATED_IMPLEMENTATION,
    ),
    _obs(KnowledgeKind.ACTOR, "Orchestrator splits and routes work.", REPEATED_IMPLEMENTATION),
    _obs(
        KnowledgeKind.ACTOR,
        "Aggregator waits for N results and emits the final report in the fanout and "
        "aggregate pattern.",
    ),
    _obs(
        KnowledgeKind.ACTOR,
        "The 'spreadsheet' skill is a specialist loaded from a bundled skills directory "
        "within the vibe skill set.",
        HARNESS_NOISE,
    ),
)

_RULES: tuple[ExtractedObservation, ...] = (
    # The profile cluster: one decision, one contradicting rule, and repetition.
    _obs(KnowledgeKind.RULE, ADMIN_PROFILE_RULE_TEXT, PROFILE_CONFLICT, AWS_PROFILE),
    _obs(
        KnowledgeKind.RULE,
        "Use separate profiles or role assumption to prevent accidental use of admin "
        "tooling from runtime hosts.",
        AWS_PROFILE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Admin-only behavior must be kept out of bin/client/.",
        AWS_PROFILE,
        REPEATED_IMPLEMENTATION,
    ),
    # Dead-letter queue: nine statements, one concept.
    _obs(
        KnowledgeKind.RULE,
        "A poison message must be routed to the DLQ after reaching the max receive count.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "On a bad payload, publish a failure and let the DLQ isolate the message.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Dead-letter messages should be inspected, categorized, and replayed only after "
        "the underlying failure mode is understood.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Alert when DLQ message count is greater than zero for critical queues.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Peeking the DLQ must use VisibilityTimeout=0 so that messages are not consumed.",
        DEAD_LETTER_QUEUE,
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.RULE,
        "When the DLQ view warns that a queue is missing, the resolution is to run "
        "scripts/aws-setup/create_dlq.sh.",
        DEAD_LETTER_QUEUE,
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.RULE,
        "In multi-account deployments, the queue owner account must retain control of "
        "resource policy, encryption, and dead-letter handling.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    # Visibility timeout / retry.
    _obs(
        KnowledgeKind.RULE,
        "On a transient dependency failure, let the visibility timeout expire so the "
        "message is retried automatically.",
        VISIBILITY_TIMEOUT,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "If execution fails, the worker should publish a failure event and let SQS retry "
        "or redrive the message according to queue configuration.",
        VISIBILITY_TIMEOUT,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "A worker must delete the message only when it is safe to do so, meaning not "
        "before task completion.",
        IDEMPOTENT_CONSUMER,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(KnowledgeKind.RULE, SAFE_DELETE_ANSWER_TEXT, IDEMPOTENT_CONSUMER),
    _obs(
        KnowledgeKind.RULE,
        "Workers are stateless: they may poll, process, report, and exit.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Monitoring observes without blocking the workflow.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Alert when visible backlog grows while consumers appear healthy.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "If the backlog grows, the response is to add workers or fix the slow stage.",
        MECHANICALLY_CLASSIFIABLE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Worker scaling should be driven by queue pressure signals: visible messages, "
        "not-visible messages, oldest message age, and DLQ growth.",
        MECHANICALLY_CLASSIFIABLE,
        REPEATED_IMPLEMENTATION,
    ),
    # Least-privilege IAM: six statements of one rule.
    _obs(
        KnowledgeKind.RULE,
        "Runtime and client hosts should use least-privilege IAM permissions.",
        LEAST_PRIVILEGE_IAM,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Broad permissions must be reduced over time and old credentials reviewed.",
        LEAST_PRIVILEGE_IAM,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Secret material is not written to logs or files by the script.",
        LEAST_PRIVILEGE_IAM,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Destructive admin operations must require confirm_destructive_action.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Deletion of the old access key must occur only after the new key is confirmed working.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Learning must begin with standard queues, long polling, visibility timeout, and "
        "dead-letter queues before advancing to IAM scoping and CloudWatch metrics.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "transactionUuid correlates multiple messages across one workflow.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Aggregators are responsible for deciding how to combine outputs.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "On result upload failure, retry the task or publish a partial failure.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "A second router or control plane must not be introduced.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "The fixed six-stage governed runtime must not be bypassed.",
        HARNESS_NOISE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Child-governed completion is local-scope only and cannot justify root-level "
        "completion language.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "The requirement-declared proof boundary must be reused as the starting point for "
        "generalization evidence rather than establishing a new boundary.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "The frozen Baseline Document Quality Dimensions section is the authoritative list "
        "of dimensions artifact review must cover.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "TDD exceptions must be reused from the frozen Code Task TDD Exceptions section "
        "when strict failing-first sequencing is intentionally exempted.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Missing document-dimension coverage must be treated as a manual-review-required "
        "hit and kept separate from UI baselines.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Governed vibe must explicitly record whether specialist execution happened, stayed "
        "advisory, or remained unresolved before closeout.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "A 'missing environment variable' error on submit indicates the Lambda environment "
        "was not correctly set by deploy_lambdas.sh.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Use mocks for boto3 calls in tests.",
        IMPLEMENTATION_DETAIL,
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Targeted verification passes or fails explicitly; silence does not count as success.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Re-run mirror sync and parity validation before release claims.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Known partials are documented in the MVP README and web README instead of being "
        "hidden as future work.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Binary payloads must not be sent through SQS; large data goes to S3 with a pointer "
        "in the message.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.RULE,
        "The secret access key appears only once and AWS does not let it be retrieved later.",
        OBSERVED_FACT,
        CONFIRMATION_ABANDONED,
        confirm=True,
    ),
    _obs(
        KnowledgeKind.RULE,
        "Long polling must be preferred over short polling on every runtime queue.",
        REPEATED_IMPLEMENTATION,
    ),
)

_ASSUMPTIONS: tuple[ExtractedObservation, ...] = (
    _obs(
        KnowledgeKind.ASSUMPTION,
        "The default AWS profile for IAM operations is aws-compute-lab-admin.",
        AWS_PROFILE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "The automation currently runs under a named AWS CLI profile called aws-compute-lab-admin.",
        AWS_PROFILE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "The admin profile aws-compute-lab-admin must be confirmed working before any other "
        "steps are executed.",
        AWS_PROFILE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "The default AWS region for IAM operations is ca-central-1.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "Queue-driven architecture is the chosen approach for the system under discussion.",
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "Lambda is only appropriate for lightweight preprocessing; heavier workloads require EC2.",
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "Work units in the target domain are larger than a single request/response cycle.",
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "Local development may run without any AWS credentials for offline checks.",
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "At least two or three IAM users exist in the lab account, so iam_audit.py produces "
        "non-empty output.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "The guard preventing deletion of a user's only active key is intentionally kept "
        "simple rather than more sophisticated.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "All required governed runtime prerequisite paths are already present on the "
        "filesystem before work begins.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.ASSUMPTION,
        "A specialist loaded from a runtime-mirror file is not yet active; it is pending "
        "until the current session begins.",
        HARNESS_NOISE,
    ),
)

_REQUIREMENTS: tuple[ExtractedObservation, ...] = (
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The environment variable AWS_PROFILE must be exported as aws-compute-lab before "
        "running the SQS client.",
        AWS_PROFILE,
        PROFILE_CONFLICT,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Lambda handlers must be packaged and deployed using deploy_lambdas.sh with the "
        "aws-compute-lab-admin profile and a specified region.",
        AWS_PROFILE,
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The SQS queue configuration must be verifiable with aws sqs list-queues --profile "
        "aws-compute-lab.",
        AWS_PROFILE,
        IMPLEMENTATION_DETAIL,
    ),
    # Idempotency: five statements, one requirement.
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Consumers must tolerate duplicate message delivery (idempotency).",
        IDEMPOTENT_CONSUMER,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Consumers should be idempotent because duplicate delivery is normal, especially "
        "when a consumer crashes after completing work but before deleting the message.",
        IDEMPOTENT_CONSUMER,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Retry-safe operations are required of every consumer.",
        IDEMPOTENT_CONSUMER,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Receive and delete behavior must be safe, and receive state must be tracked.",
        IDEMPOTENT_CONSUMER,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Consumers must parse and validate the message body.",
        IDEMPOTENT_CONSUMER,
        MECHANICALLY_CLASSIFIABLE,
    ),
    # Dead-letter requirements restating the rules above.
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Repeated failures must be routed into a dead-letter queue (DLQ).",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Redrive policies must be configured so repeatedly failing messages move to a "
        "dead-letter queue.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Lambda consumers must use a dead-letter queue or failure destination.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Each stage in a REST service orchestration pipeline must be able to scale "
        "independently and expose its own dead-letter queue.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The web console must inspect the DLQ in real mode through its local /api/dlq "
        "endpoint without consuming messages.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "For Lambda consumers, the SQS visibility timeout must be set longer than the "
        "expected processing time.",
        VISIBILITY_TIMEOUT,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Consumers must complete work within the visibility timeout.",
        VISIBILITY_TIMEOUT,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The get-attrs command must show attributes including VisibilityTimeout and "
        "MessageRetentionPeriod.",
        VISIBILITY_TIMEOUT,
        IMPLEMENTATION_DETAIL,
    ),
    # Observed repository facts. Doc 17's docker-compose case.
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The SQS package exposes SqsClient from aws_compute_lab.sqs.client.",
        OBSERVED_FACT,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Job, status, heartbeat, log, output, and manifest contracts must be backed by S3.",
        OBSERVED_FACT,
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Audit files must be written under ~/.aws-compute-lab/, specifically "
        "~/.aws-compute-lab/messages/sqs/ and ~/.aws-compute-lab/state/sqs/.",
        OBSERVED_FACT,
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Browser credentials must be isolated from other runtime credentials in "
        "compute_lab_mvp/web/server.py.",
        OBSERVED_FACT,
    ),
    # Implementation detail: CLI surface, flags, config keys.
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The send command must accept an input file, a service name, a service operation, "
        "and a config file.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The peek command must inspect a queue without deleting messages.",
        IMPLEMENTATION_DETAIL,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The peek subcommand must show the message without removing it from the queue.",
        IMPLEMENTATION_DETAIL,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The iam_audit.py tool must support a --key-age-warning-days flag with a default "
        "warning threshold for aging keys.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The --wait long-poll seconds argument must be between 0 and 20.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Receive batch size and long-poll wait time must be validated locally.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "~/.aws-compute-lab/config/sqs_services.yaml must be created from "
        "examples/client/sqs_services.yaml with real account IDs and queue URLs.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Each service must declare a default_queue and a queues map containing queue_url entries.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The client must track sent messages under a send category, structured received "
        "messages under messages, and unstructured received messages under common.",
        IMPLEMENTATION_DETAIL,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Application logs must include messageUuid, transactionUuid, serviceName, operation, "
        "queue name, processing duration, and success/failure classification.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "CloudWatch must be used for metrics, logs, dashboards, and alarms.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Dashboards must be created for visible messages, messages not visible, age of oldest "
        "message, sent/received/deleted counts, empty receives, and DLQ depth.",
        MECHANICALLY_CLASSIFIABLE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Producers should send only small control messages: job name, input/output S3 paths, "
        "configuration references, correlation IDs, and retry metadata.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "A status or result queue must exist for workers to publish back to a local monitor "
        "or dashboard.",
        MECHANICALLY_CLASSIFIABLE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Status consumers must be able to update dashboards, notify operators, or trigger "
        "aggregation jobs.",
        MECHANICALLY_CLASSIFIABLE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The worker must not need to know who initiated the request.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Runtime IAM must be scoped to specific queue ARNs and only the required actions.",
        LEAST_PRIVILEGE_IAM,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The EC2 worker must run under an instance role scoped only to SQS, S3, and "
        "self-termination.",
        LEAST_PRIVILEGE_IAM,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "An instance profile with least-privilege SQS permissions must be attached to the "
        "worker instance.",
        LEAST_PRIVILEGE_IAM,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Deployment scripts must cover API Gateway, Lambda, workers, DLQ, and schedules.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The SQS and IAM subsystems must remain usable outside the MVP.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Local tracking must answer whether a message was sent by this host, whether a "
        "received message was tracked before delete, and what the receive history was.",
        MECHANICALLY_CLASSIFIABLE,
        CONFIRMATION_ABANDONED,
        confirm=True,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "A cloud worker must be able to receive from the resolved queue using the same "
        "message contract as a local worker.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Job metadata must be written durably to S3 before the SQS message is sent.",
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Worker outputs must be stored in S3 and referenced by pointer rather than inlined.",
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The stuck-job reconciler must run as a scheduled Lambda.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "An execution plan must exist before implementation begins.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Targeted repo verification must be run for changed surfaces.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "One meaningful unhappy-path or validation-path interaction must be exercised and its "
        "behavior recorded against the frozen requirement.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The protocolsio-integration specialist skill requires a bounded specialist subtask "
        "contract, frozen requirement context, and relevant source files as inputs.",
        HARNESS_NOISE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The spreadsheet specialist requires a bounded specialist subtask contract, frozen "
        "requirement context, and relevant source files as inputs.",
        HARNESS_NOISE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Separation must be maintained because the repository contains both privileged "
        "provisioning tools and a runnable MVP application.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "The MVP must own its own shared package, client, Lambda handlers, worker code, web "
        "console, config, packaging, and local docs.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.REQUIREMENT,
        "Separate queues per workflow must prevent one backed-up workflow from blocking all "
        "other workflows.",
        MECHANICALLY_CLASSIFIABLE,
        REPEATED_IMPLEMENTATION,
    ),
)

_UNKNOWNS: tuple[ExtractedObservation, ...] = (
    # Answerable from the corpus itself. Outcome 8.
    _obs(
        KnowledgeKind.UNKNOWN,
        SAFE_DELETE_QUESTION_TEXT,
        CHUNK_LOCAL_QUESTION,
        IDEMPOTENT_CONSUMER,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What constitutes 'conservative' receive/delete behavior — at-least-once delivery, "
        "explicit delete only after processing, or visibility timeout management?",
        CHUNK_LOCAL_QUESTION,
        IDEMPOTENT_CONSUMER,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What guarantees are required for 'receiving messages safely' — at-least-once "
        "delivery, idempotency, or visibility timeout handling?",
        CHUNK_LOCAL_QUESTION,
        IDEMPOTENT_CONSUMER,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "Which AWS profile do the SQS admin commands run under?",
        CHUNK_LOCAL_QUESTION,
        AWS_PROFILE,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What constitutes 'large' data for the purpose of the rule against sending binary "
        "payloads through SQS?",
        CHUNK_LOCAL_QUESTION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What criteria determine when a backlog is large enough to trigger automated EC2 "
        "worker launch?",
        CHUNK_LOCAL_QUESTION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What mechanism or format is used for the status events that workers publish for "
        "dashboard consumption?",
        CHUNK_LOCAL_QUESTION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What threshold of delivery attempts triggers the redrive policy move to the "
        "dead-letter queue?",
        CHUNK_LOCAL_QUESTION,
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What threshold of failures triggers transfer to the dead-letter queue, and is it "
        "configurable per queue?",
        CHUNK_LOCAL_QUESTION,
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    # Pipeline residue: the extractor reporting on its own truncated input.
    _obs(
        KnowledgeKind.UNKNOWN,
        "The document ends mid-section under 'Troubleshooting Hints' with no content "
        "provided; the intended guidance is unclear.",
        TRUNCATION_ARTIFACT,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "The full name and content of the docs_mvp/codex_wor... artifact referenced in the "
        "task focus — the text is truncated and the path is not recoverable.",
        TRUNCATION_ARTIFACT,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "The document is cut off mid-section for iam_create_user.py; its requirements, "
        "expected output, and demo steps are not specified.",
        TRUNCATION_ARTIFACT,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What the aws-sqs-admin demo steps and expected output are — the text cuts off "
        "before describing them.",
        TRUNCATION_ARTIFACT,
    ),
    # Harness questions: about the agent run, not about the project.
    _obs(
        KnowledgeKind.UNKNOWN,
        "What constitutes the six stages of the governed runtime that must not be bypassed?",
        HARNESS_NOISE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What are the six stages of the governed runtime referenced as fixed?",
        HARNESS_NOISE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What constitutes 'frozen requirement context' and how it is determined or versioned "
        "is not defined in this text.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What criteria determine whether a specialist candidate is adopted by the host versus "
        "remaining a non-adopted candidate?",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "The full context and meaning of 'Deferred from Studio' is not explained.",
        HARNESS_NOISE,
    ),
    # Genuinely open, and genuinely the owner's to settle.
    _obs(KnowledgeKind.UNKNOWN, DEFERRED_LAYER_TEXT, DEFERRED_DECISION),
    _obs(
        KnowledgeKind.UNKNOWN,
        "Whether aws-cleanup is a functional tool or a skeleton, since its behavior has not "
        "been verified.",
        DEFERRED_DECISION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "It is not stated which queue types, standard or FIFO, are required by the SQS subsystem.",
        DEFERRED_DECISION,
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "The scope and design of future dashboards, replay commands, worker orchestration, "
        "and dead-letter replay flows are not yet defined.",
    ),
    _obs(
        KnowledgeKind.UNKNOWN,
        "What specific features the web console must include is not stated in this text.",
    ),
)

_CONSTRAINTS: tuple[ExtractedObservation, ...] = (
    _obs(
        KnowledgeKind.CONSTRAINT,
        "The AWS profile used by the scripts is aws-compute-lab-admin and the region is "
        "ca-central-1.",
        AWS_PROFILE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "The tooling is explicitly not intended to replace a full identity platform.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "The solution must work from normal developer networks without special firewall or "
        "VPN configuration.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "Reusable SQS and IAM tooling must remain a distinct architectural track under bin/ "
        "and lib/python/.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "Inputs are frozen: requirement doc, runtime input packet, and source task are fixed "
        "and must not be altered.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "Anti-proxy-goal-drift tier is Tier C.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "The completion state for this task is partial, not full.",
        HARNESS_NOISE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "No grade floor is required for outputs.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "Parallel work must use disjoint write scopes.",
        HARNESS_NOISE,
    ),
    _obs(
        KnowledgeKind.CONSTRAINT,
        "Each artifact set must have exactly one owner.",
        HARNESS_NOISE,
    ),
)

_DECISIONS: tuple[ExtractedObservation, ...] = (
    _obs(
        KnowledgeKind.DECISION,
        ADMIN_PROFILE_DECISION_TEXT,
        PROFILE_CONFLICT,
        AWS_PROFILE,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "The IAM scripts default to profile aws-compute-lab-admin and region ca-central-1 to "
        "keep the rest of the repository consistent, even though IAM is global.",
        AWS_PROFILE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "Long polling is preferred over short polling to reduce empty responses and cost.",
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "A dead-letter queue receives messages that fail too many times, rather than "
        "discarding or retrying them indefinitely inline.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "DLQ growth is treated as a signal for repeated failure rather than transient load.",
        DEAD_LETTER_QUEUE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "Service configuration is externalised to examples/client/sqs_services.yaml rather "
        "than inlined in code.",
        MECHANICALLY_CLASSIFIABLE,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "Worker outputs are stored in S3 and later combined by an aggregator.",
        MECHANICALLY_CLASSIFIABLE,
        REPEATED_IMPLEMENTATION,
    ),
    _obs(
        KnowledgeKind.DECISION,
        "The memory system operates at a decision_focused disclosure level when injecting "
        "context into requirement freezing.",
        HARNESS_NOISE,
    ),
)

OBSERVATIONS: tuple[ExtractedObservation, ...] = (
    _GOALS + _ACTORS + _RULES + _ASSUMPTIONS + _REQUIREMENTS + _UNKNOWNS + _CONSTRAINTS + _DECISIONS
)


def count_by_kind(
    observations: tuple[ExtractedObservation, ...] = OBSERVATIONS,
) -> dict[str, int]:
    """Return extracted-row counts by knowledge kind."""

    return dict(Counter(item.kind.value for item in observations))


def observations_for(*cases: str) -> tuple[ExtractedObservation, ...]:
    """Return observations tagged with any of the named regression cases."""

    wanted = frozenset(cases)
    return tuple(item for item in OBSERVATIONS if item.cases & wanted)


# --- Ground truth for `EPI-3b` ----------------------------------------------
#
# `D-110`. The gates above assert a *fraction placed*, and
# `test_statements_that_name_their_own_area_are_placed` asserts these rows are
# placed **somewhere**. Neither asserts *where*, and until this table existed
# neither could: nothing in the fixture recorded an expected area. A classifier
# that placed enough rows wrongly would have scored as a pass.
#
# That is the half of `ADR-0015`'s objection `EPI-5b` did not retire. `EPI-5b`
# stopped auto-placement inflating readiness — a placed link reaches `evidenced`,
# never `sufficient`. It says nothing about a quality attribute filed under
# functional requirements, which is still coverage a person has to unpick.
#
# Written **before** the classifier, deliberately. Labels written by somebody who
# had already seen what the classifier does would drift toward agreeing with it,
# and ground truth that cannot fail is not ground truth.

EXPECTED_AREAS: Final[Mapping[str, str]] = {
    # Rules. Structure and content of the model, versus a condition to verify.
    "Workers are stateless: they may poll, process, report, and exit.": ("domain_model_and_data"),
    "transactionUuid correlates multiple messages across one workflow.": ("domain_model_and_data"),
    "Aggregators are responsible for deciding how to combine outputs.": ("domain_model_and_data"),
    "Binary payloads must not be sent through SQS; large data goes to S3 with a "
    "pointer in the message.": "domain_model_and_data",
    "Deletion of the old access key must occur only after the new key is confirmed "
    "working.": "acceptance_criteria",
    "Use mocks for boto3 calls in tests.": "acceptance_criteria",
    "Targeted verification passes or fails explicitly; silence does not count as "
    "success.": "acceptance_criteria",
    # Requirements.
    "Consumers must parse and validate the message body.": "functional_requirements",
    "The web console must inspect the DLQ in real mode through its local /api/dlq "
    "endpoint without consuming messages.": "functional_requirements",
    "A status or result queue must exist for workers to publish back to a local "
    "monitor or dashboard.": "functional_requirements",
    "Status consumers must be able to update dashboards, notify operators, or "
    "trigger aggregation jobs.": "functional_requirements",
    "Local tracking must answer whether a message was sent by this host, whether a "
    "received message was tracked before delete, and what the receive history was.": (
        "functional_requirements"
    ),
    "Job, status, heartbeat, log, output, and manifest contracts must be backed by "
    "S3.": "domain_model_and_data",
    "Application logs must include messageUuid, transactionUuid, serviceName, "
    "operation, queue name, processing duration, and success/failure "
    "classification.": "domain_model_and_data",
    "Producers should send only small control messages: job name, input/output S3 "
    "paths, configuration references, correlation IDs, and retry metadata.": (
        "domain_model_and_data"
    ),
    "CloudWatch must be used for metrics, logs, dashboards, and alarms.": (
        "interfaces_and_integrations"
    ),
    "The worker must not need to know who initiated the request.": "quality_attributes",
    "The SQS and IAM subsystems must remain usable outside the MVP.": "quality_attributes",
    "Separate queues per workflow must prevent one backed-up workflow from blocking "
    "all other workflows.": "quality_attributes",
    # Constraints.
    "The tooling is explicitly not intended to replace a full identity platform.": (
        "scope_and_boundaries"
    ),
    "Reusable SQS and IAM tooling must remain a distinct architectural track under "
    "bin/ and lib/python/.": "scope_and_boundaries",
    "The solution must work from normal developer networks without special firewall "
    "or VPN configuration.": "constraints_and_assumptions",
    # Decisions.
    "Service configuration is externalised to examples/client/sqs_services.yaml "
    "rather than inlined in code.": "delivery_and_operations",
    "Worker outputs are stored in S3 and later combined by an aggregator.": (
        "interfaces_and_integrations"
    ),
}
"""The area each mechanically-classifiable statement belongs in.

Not all 37 of them. The rows left out are left out for a reason worth reading,
and it is `AREA-UNREACHABLE` on the checklist rather than an omission.
"""

AREA_UNREACHABLE_FOR_KIND: Final[Mapping[str, str]] = {
    "Monitoring observes without blocking the workflow.": "quality_attributes",
    "Alert when visible backlog grows while consumers appear healthy.": ("delivery_and_operations"),
    "If the backlog grows, the response is to add workers or fix the slow stage.": (
        "delivery_and_operations"
    ),
    "Worker scaling should be driven by queue pressure signals: visible messages, "
    "not-visible messages, oldest message age, and DLQ growth.": "quality_attributes",
    "On result upload failure, retry the task or publish a partial failure.": (
        "quality_attributes"
    ),
    "Known partials are documented in the MVP README and web README instead of "
    "being hidden as future work.": "delivery_and_operations",
    "Deployment scripts must cover API Gateway, Lambda, workers, DLQ, and "
    "schedules.": "delivery_and_operations",
}
"""Statements whose area *is* plain, and is one their kind cannot reach.

Found by trying to label them (`D-110`). Every one is a `rule` or a `requirement`
about monitoring, scaling, resilience, documentation or deployment — so it
belongs in `quality_attributes` or `delivery_and_operations`, and
`SOFTWARE_TEMPLATE` lets neither area accept a `rule`, nor
`delivery_and_operations` accept a `requirement`.

**No classifier can place these correctly**, because the correct answer is not
among its options. Whatever `EPI-3b` does with them will be wrong, and the fix
is a question about the template's kind-to-area mapping, which `RUN-C1` rules
may not be widened casually. Recorded here rather than mislabelled, so the
classifier is never scored on an answer that does not exist.
"""

AMBIGUOUS_DESPITE_THE_TAG: Final[tuple[str, ...]] = (
    "A cloud worker must be able to receive from the resolved queue using the same "
    "message contract as a local worker.",
    "Dashboards must be created for visible messages, messages not visible, age of "
    "oldest message, sent/received/deleted counts, empty receives, and DLQ depth.",
    "Separation must be maintained because the repository contains both privileged "
    "provisioning tools and a runnable MVP application.",
    "The MVP must own its own shared package, client, Lambda handlers, worker code, "
    "web console, config, packaging, and local docs.",
    "The stuck-job reconciler must run as a scheduled Lambda.",
)
"""Rows the `MECHANICALLY_CLASSIFIABLE` tag over-claims.

Also found by trying to label them (`D-110`). Each has two defensible areas and
no way to choose between them from the sentence: a dashboard requirement is
functional or a quality attribute depending on why it exists; a scheduled
Lambda is a function of the product or a deployment fact.

They are left unlabelled **on purpose**. Labelling them would put a coin flip
into the ground truth and score a classifier as wrong for agreeing with the
other reasonable reading. The tag stays on them, because
`test_statements_that_name_their_own_area_are_placed` asking that they be
placed *somewhere* is still right — it is only *where* that cannot be graded.
"""


def collapse_key(observation: ExtractedObservation) -> tuple[str, str]:
    """Match Memory's identical-statement identity (kind + normalised text)."""

    return observation.kind.value, " ".join(observation.content.split()).casefold()


_HEADLINE_ACTUAL = count_by_kind()
if dict(HEADLINE_COUNTS) != _HEADLINE_ACTUAL:
    raise RuntimeError(
        "AWS Compute Lab corpus headline counts drifted: "
        f"expected {dict(HEADLINE_COUNTS)}, got {_HEADLINE_ACTUAL}"
    )
