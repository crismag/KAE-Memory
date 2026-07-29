# EC2 host

AWS-specific provisioning. Everything reusable on another Linux host lives in
[`../../server/`](../../server/) and is **invoked** from here, never duplicated.

EC2 with systemd is the hosted reference deployment (ADR-0017, closing OQ-018).
It satisfies ADR-0013's required profile directly, so the required and optional
profiles collapse into one shape.

## Instance assumptions

| Property | Value |
| --- | --- |
| OS | Ubuntu 24.04 LTS |
| Size | `t3.small` is sufficient — two Python processes and nginx; the database is elsewhere |
| Storage | 20 GB gp3. No durable state lives here |
| Instance profile | Required, see below. **No access keys** |
| Public IP | Needed only if the frontend is hosted elsewhere |

The instance is disposable by design: CockroachDB Cloud holds everything durable,
so replacing the host loses nothing. That is what makes the recovery
demonstration honest rather than staged.

## Security group

| Port | Source | Why |
| --- | --- | --- |
| 443 | `0.0.0.0/0` once TLS is configured | nginx |
| 80 | `0.0.0.0/0` | nginx, redirecting to 443 |
| 22 | **your IP only** | administration |
| 8000 | **nothing** | the API binds to loopback and is proxied |

**Port 8000 must never be open.** The API has no authentication (ADR-0014). It
binds to `127.0.0.1` by default, and that default is the last line of defence
rather than the only one.

## Instance role

Attach [`iam-policy.example.json`](iam-policy.example.json) to the instance
profile. It grants two things:

- `bedrock:InvokeModel` on the approved models — Titan for embeddings (ADR-0008)
  and Claude for extraction (ADR-0006);
- writes to its own CloudWatch log group.

Nothing else. No S3, no Secrets Manager, no EC2 self-management, and **no
long-lived access keys anywhere**.

> The Bedrock permission is the one that matters for correctness, not just
> operations: without it the extraction adapter falls back to the offline
> fixture, and the semantic retrieval evaluation cannot run at all. If a
> deployment reports plausible-looking results with `model:
> "deterministic-fixture"` in its run summaries, this policy is missing.

## Bootstrap

[`user-data.sh`](user-data.sh) runs once at first boot: installs Python, git,
nginx and curl, clones the repository, runs the generic installer, and enables
the reverse-proxy configuration.

It deliberately does **not** start the services. They need `KAE_DATABASE_URL`
first, and a unit that starts before its configuration exists produces a restart
loop and a misleading `systemctl status`.

After boot:

```bash
sudo -e /etc/kae-memory/api.env       # KAE_DATABASE_URL=...
sudo -e /etc/kae-memory/worker.env    # KAE_DATABASE_URL=...
sudo -u kae /opt/kae-memory/.venv/bin/alembic -c /opt/kae-memory/alembic.ini upgrade head
sudo systemctl enable --now kae-api kae-worker
curl -s localhost:8000/health
```

## Configuring a new AWS account

The steps, in order. **Do not paste credentials into a chat, a commit, or an
issue** — every value below belongs in the instance profile or in a root-owned
environment file on the host.

1. **Enable Bedrock model access** in the region you will use — Titan Text
   Embeddings V2, and Claude if live extraction is wanted. This is a console
   action per region and is separate from IAM: the policy above grants nothing if
   model access has not been requested.
2. **Create the instance role** from `iam-policy.example.json` and attach it to
   an instance profile.
3. **Launch the instance** with that profile, the security group above, and
   `user-data.sh` as user data.
4. **Create the CockroachDB Cloud user and database**, then put its connection
   string in both environment files.
5. **Verify** with `curl localhost:8000/health` — it reports the applied
   migration revision, which is the cheapest proof the database is reachable and
   current.

Region should match the CockroachDB Cloud cluster's region. Cross-region adds
latency to every transaction, and this application is transaction-heavy by
design.
