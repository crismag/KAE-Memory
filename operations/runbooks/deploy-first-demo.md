# Runbook — first demonstration deployment

Brings up the demonstration described by ADR-0017: one EC2 instance running the
API and worker under systemd, the workspace served as static files, and
CockroachDB Cloud holding everything durable.

Roughly thirty minutes, most of it waiting for AWS.

## Before you start

You need: an AWS account with Bedrock model access enabled in your region, a
CockroachDB Cloud cluster, and a domain if you want TLS.

**Do not put credentials in the repository, a commit message, an issue, or a
chat.** Everything secret belongs in the instance profile or in a root-owned
environment file on the host (FR-018).

## 1. CockroachDB Cloud

Create a database and a SQL user for it. Keep the connection string; it contains
the password.

```text
cockroachdb+psycopg://USER:PASSWORD@HOST:26257/DATABASE?sslmode=verify-full
```

Note the **scheme**: `cockroachdb+psycopg`, not `postgresql`. The dialect matters
— SQLAlchemy cannot parse the cluster's version string without it.

## 2. AWS

1. **Enable Bedrock model access** for Titan Text Embeddings V2, and Claude if
   you want live extraction. Per region, in the console. IAM alone is not enough.
2. Create an IAM role from `deploy/aws/ec2/iam-policy.example.json` and an
   instance profile from it.
3. Launch Ubuntu 24.04, `t3.small`, with that instance profile, the security
   group from `deploy/aws/ec2/README.md`, and `deploy/aws/ec2/user-data.sh` as
   user data.

**Port 8000 stays closed.** The API has no authentication.

## 3. Configure and start

```bash
ssh ubuntu@INSTANCE
sudo -e /etc/kae-memory/api.env        # KAE_DATABASE_URL=cockroachdb+psycopg://...
sudo -e /etc/kae-memory/worker.env     # the same value
sudo -u kae /opt/kae-memory/.venv/bin/alembic -c /opt/kae-memory/alembic.ini upgrade head
sudo systemctl enable --now kae-api kae-worker
curl -s localhost:8000/health
```

Healthy output names the applied revision:

```json
{"status":"ok","database":"up","migration_revision":"0005","version":"0.1.0"}
```

`"database":"down"` means the connection string is wrong or the cluster's IP
allowlist excludes the instance. A null revision means migrations have not run.

## 4. Walk the demonstration

KAE-Memory serves no interface of its own (ADR-0026). Drive it through an MCP
client or the HTTP API; a browser workspace is KAE-Studio's, in its own
repository, and is not deployed from here.

Create a project, open a session, submit an idea, watch the requirements run
complete, confirm knowledge, assign areas, run the Review agent, read the
findings, open the blueprint, and trace a statement back to the message that
produced it.

If a run stays `pending`, the worker is not claiming: `systemctl status
kae-worker` and `journalctl -u kae-worker -n 50`.

If run summaries show `"model": "deterministic-fixture"`, extraction fell back
offline — Bedrock model access or the instance-role policy is missing. The
demonstration still works; it just is not using a model, and saying otherwise
would be untrue.

## 6. Tear down

An unauthenticated API should not be left running. Terminate the instance; the
CockroachDB cluster keeps every durable thing, so bringing it back is this
runbook again rather than a restore.
