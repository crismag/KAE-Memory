# AWS-specific deployment

Only assets genuinely tied to AWS. Anything reusable on another Linux host
belongs in [`../server/`](../server/), and **must not be duplicated here**.

```text
deploy/aws/ec2/     AWS-specific provisioning
deploy/server/      reusable Linux application installation
```

EC2 files describe how an instance is provisioned and then **invoke** the generic
installation. They never restate systemd units or reverse-proxy configuration.

## Planned scope

`ec2/` and `sqs/` are created when they hold real files. Lambda, Lightsail, API
Gateway, CloudWatch, ECS, Fargate, Route 53, S3, and Secrets Manager directories
are **not** created until those services are actively implemented.

### `ec2/`

Expected: `README.md`, `user-data.sh`, `iam-policy.example.json`. Documents
instance and OS assumptions, security-group ports, instance-role requirements,
and the bootstrap sequence.

AWS access on the instance should use an **IAM instance role**. Access keys must
never be committed.

### `sqs/`

Expected: `README.md`, `create-queue.sh`, `queue-policy.example.json`. One work
queue to start, a dead-letter queue when implemented, queue URL or name as
output, an appropriate visibility timeout, and least-privilege API and worker
permissions.

## SQS must stay a wake-up mechanism

Messages carry **identifiers, not authoritative state**:

```json
{ "run_id": "run_identifier", "message_type": "agent_run_requested" }
```

CockroachDB retains run status, lease ownership, lease expiry, execution
attempts, checkpoints, the final result, and failure information. That is not a
stylistic preference — ADR-0007 makes CockroachDB the single authority for
runnable work precisely so that recovery does not depend on a message broker's
delivery semantics.

The worker must remain **safe under duplicate delivery**. It already is: claiming
is a compare-and-swap on a monotonic fencing token, and execution is
at-least-once by design. A duplicated SQS message causes a redundant claim
attempt that loses the swap, not a duplicated run.

## Two decisions this directory anticipates but does not make

**SQS is not yet an approved architectural element.** No ADR authorises it. It is
compatible with ADR-0007 as described above — a wake-up signal over a database
that remains authoritative — but adding a second delivery path is a decision, and
this repository records decisions before implementing them. It also has no
current purpose: the worker has no daemon loop to wake (ADR-0013). An ADR should
precede any file in `sqs/`.

**EC2 is not the runtime ADR-0013 named.** That decision made Docker Compose or an
OS process supervisor the *required* profile and ECS on Fargate the *preferred
optional* production reference. EC2 with systemd satisfies the required profile
exactly. What changes is the optional reference — from a managed container
runtime to a self-managed instance — which is a smaller decision but still one
worth recording rather than absorbing silently.

Both are tracked as open questions in [`../../project-model.yaml`](../../project-model.yaml).

## Accepted limit

A supervisor restarting a process on one instance is not a scheduler replacing a
task in a cluster: it does not exercise image pull, IAM, networking, or cross-AZ
placement. The required profile proves the **recovery protocol**; only a real
hosted run proves the **deployment**. Say which one a demonstration is showing.
