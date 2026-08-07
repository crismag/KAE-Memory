# Runbook — enablement sequence

The ordered path from "runs on my machine" to "deployed for a demonstration".
Five stages, each with a **verification gate**. Do not start a stage until the
previous gate passes: every stage depends on the one before it, and a failure
diagnosed two stages late costs more than the wait.

| Stage | What it enables | Needs |
| --- | --- | --- |
| 1 | KAE-Memory locally, offline | Docker, Python |
| 2 | AWS credentials on your machine | AWS account |
| 3 | Live extraction and embeddings | Bedrock model access |
| 4 | Retrieval quality proven | Stage 3 |
| 5 | Deployed on EC2 | Stages 2–4 |

Five stages. There is no frontend stage: KAE-Memory ships no interface and
builds none (ADR-0026). What a person looks at belongs to KAE-Studio, in its own
repository, and is not deployed from here.

---

## Where credentials go

Decide this once, now, because getting it wrong is the expensive mistake.

| Secret | Correct location | Never |
| --- | --- | --- |
| AWS access keys, local development | `~/.aws/credentials`, named profile | The repository. A `.env`. A commit. A chat message |
| AWS access on EC2 | **Instance role.** No keys at all | Any file on the instance |
| Database connection string, local | `.env` (gitignored) or the shell | Anywhere tracked by git |
| Database connection string, EC2 | `/etc/kae-memory/*.env`, root-owned, `0640` | The application directory |

**`~/.aws/credentials` is the right place for local development** — it is outside
the repository, the AWS SDK finds it without configuration, and it is the
convention every AWS tool already expects. The application never reads keys
directly: it reads `AWS_PROFILE` and `AWS_REGION` from the environment and lets
boto3 resolve the rest.

`.env` carries **references**, never keys:

```bash
AWS_PROFILE=kae-memory
AWS_REGION=us-east-1
```

That distinction is the whole point. A `.env` naming a profile is harmless if it
leaks. A `.env` containing a secret access key is an incident.

On EC2 there are **no keys**. An instance role issues short-lived credentials
automatically, and a long-lived key on a public-facing host is the single most
common way an AWS account is compromised.

---

## Stage 1 — Local, offline

```bash
make install
make dev
```

**Gate.** `curl localhost:8000/health` reports `status: ok` with a migration
revision. Through the API or an MCP client you can create a project, submit an
idea, watch a run reach `succeeded`, confirm knowledge, assign an area, see
readiness move, and trace a blueprint statement back to your own words.


Nothing here needs AWS. If this gate does not pass, no later stage will.

---

## Stage 2 — AWS credentials locally

### 2.1 Create a dedicated IAM user

Not your admin user. A user whose only permission is invoking the two approved
models, so a leaked key cannot do anything else.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "InvokeApprovedModels",
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel"],
    "Resource": [
      "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0",
      "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*"
    ]
  }]
}
```

Attach it directly to the user. Create an access key for it.

### 2.2 Store the key

```bash
aws configure --profile kae-memory
# AWS Access Key ID:     ...
# AWS Secret Access Key: ...
# Default region name:   us-east-1
# Default output format: json
```

This writes `~/.aws/credentials`. Confirm the file is `0600` and outside the
repository — `aws configure` gets both right.

Then in `.env`:

```bash
AWS_PROFILE=kae-memory
AWS_REGION=us-east-1
```

**Gate.**

```bash
AWS_PROFILE=kae-memory aws sts get-caller-identity
```

Returns the new user's ARN. If it returns your admin user, the profile is not
being read.

---

## Stage 3 — Bedrock model access

**This is the step people miss.** IAM permission and model access are separate,
and the policy above grants nothing until access is requested.

1. Bedrock console, **in the region you chose**, → *Model access*.
2. Request access to **Titan Text Embeddings V2** and, for live extraction,
   **Claude**. Amazon's own models are usually granted immediately.
3. Wait for *Access granted*.

**Gate.**

```bash
AWS_PROFILE=kae-memory uv run python -c "
import boto3, json
r = boto3.client('bedrock-runtime', region_name='us-east-1').invoke_model(
    modelId='amazon.titan-embed-text-v2:0',
    body=json.dumps({'inputText': 'hello', 'dimensions': 1024, 'normalize': True}))
print('dimensions:', len(json.loads(r['body'].read())['embedding']))"
```

Expect `dimensions: 1024`.

`AccessDeniedException ... no identity-based policy allows the
bedrock:InvokeModel action` means the IAM policy is missing. The same exception
naming the *model* usually means model access was never granted. They read
almost identically; check both.

### Live extraction locally

```bash
KAE_EXTRACTION=bedrock AWS_PROFILE=kae-memory AWS_REGION=us-east-1 make dev
```

**Gate.** A requirements run's `output_summary` names a real model instead of
`"deterministic-fixture"`. If it still says fixture, the worker did not see
`KAE_EXTRACTION=bedrock`.

---

## Stage 4 — Prove retrieval quality

This is the milestone obligation that has never been met. Embeddings and the
vector index work; whether retrieval *ranks well* is unmeasured, and offline it
scores at chance level because the offline embedder models no meaning.

```bash
KAE_EVAL_LIVE_EMBEDDING=1 AWS_PROFILE=kae-memory AWS_REGION=us-east-1 \
  uv run pytest tests/retrieval/test_evaluation_fixture.py -s
```

**Gate.** `recall@8` of **75% or better**. The test enforces it and prints the
chance level beside it for comparison.

If it fails, the honest response is to record the number, not to lower the
threshold. Retrieval that scores near chance is retrieval that returns the eight
least-wrong answers, and wiring it into a demonstration would be showing off a
feature that does not work.

---

## Stage 5 — Deploy on EC2

Only after gates 1–4. Full detail:
[`deploy-first-demo.md`](deploy-first-demo.md) and
the AWS provisioning scripts, which are held outside this repository.

Summary:

1. CockroachDB Cloud database and SQL user. Scheme is
   `cockroachdb+psycopg://`, not `postgresql://`.
2. IAM **role** from `deploy/aws/ec2/iam-policy.example.json`, and an instance
   profile from it. **No access keys on the instance.**
3. Launch Ubuntu 24.04, `t3.small`, that instance profile,
   `deploy/aws/ec2/user-data.sh` as user data, and a security group where **port
   8000 is closed** and 22 is limited to your address.
4. Fill `/etc/kae-memory/{api,worker}.env`, run migrations, enable both units.
5. Put nginx in front of the API rather than exposing port 8000. ADR-0024
   requires the process to refuse to start off-loopback without tokens, so the
   reverse proxy terminates TLS and the API binds to `127.0.0.1`.

**Gate.** On the instance, `curl localhost:8000/health` reports `status: ok`
with the expected migration revision, and an authenticated request from off the
instance reaches the API through the proxy while an unauthenticated one is
refused.

**Then tear it down.** The API has no authentication.

---

## Not covered here

**Serving a user interface.** KAE-Memory is headless (ADR-0026). A deployment of
KAE-Studio is a separate procedure in a separate repository, and folding it in
here would make this runbook describe a component it does not install.

**Authentication configuration.** ADR-0024 makes tokens mandatory off-loopback.
The mechanism is not documented in this runbook yet — recorded as a gap rather
than sketched from memory.
