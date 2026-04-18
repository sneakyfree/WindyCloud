# Windy Cloud — Production Deployment

This document is the canonical runbook for bringing Windy Cloud up on
AWS. It covers infrastructure, secrets, webhooks, cron jobs, and the
order in which things must be wired. Read this top-to-bottom the
first time; after that, each section stands on its own as a reference.

> **Scope.** This file targets a single-region production deployment.
> Multi-region and DR are out of scope for launch; we'll revisit once
> we have real traffic data.

---

## 1. Topology

```
                 ┌──────────────────┐
    HTTPS  ─────▶│ ALB (us-west-2)  │
                 └────────┬─────────┘
                          │
                 ┌────────▼─────────┐        ┌────────────────┐
                 │ EC2 t3.medium    │──POST──▶ RunPod Serverless
                 │ api.windycloud   │        │ (GPU STT)      │
                 │ Ubuntu 24.04 LTS │        └────────────────┘
                 │ Docker compose   │
                 └───┬──────────┬───┘
                     │          │
           ┌─────────▼───┐  ┌───▼─────────────┐
           │ RDS Postgres│  │ Cloudflare R2   │
           │ db.t4g.small│  │ (cold storage)  │
           │ 20 GB gp3   │  │ + S3 fallback   │
           └─────────────┘  └─────────────────┘
```

**Why us-west-2 (Oregon).**

- Lowest round-trip to Cloudflare R2 POPs on the US West edge, which
  matters because every storage write is an S3-compatible POST that
  goes over the public internet (R2 has no peering inside AWS).
- Historically the cheapest mainland-US region for EC2 + RDS per the
  AWS pricing tables we track in `deploy/docs/env-vars.md`.
- Lower cold-start variance on RunPod's Oregon endpoints than
  us-east-1 based on Windy Fly's production metrics.

If you change this, update `aws_region` in
`deploy/terraform/variables.tf` and the R2 endpoint hint in
`.env.production.example`.

---

## 2. AWS infrastructure

### 2.1 EC2 — API host

| Setting | Value | Reason |
|---|---|---|
| Instance type | `t3.medium` | 2 vCPU / 4 GB matches Fargate spec used in CI |
| AMI | Ubuntu 24.04 LTS (x86_64) | Docker + compose + systemd all first-class |
| Root volume | 30 GB gp3, encrypted | Headroom for Docker image cache + logs |
| Security group | 80 / 443 public; 22 restricted to bastion CIDR | API must be behind the ALB, never direct |

Bootstrap runs `deploy/aws-setup.sh` via `user_data`. It installs
Docker, pulls the image from GHCR, and writes `/etc/systemd/system/
windycloud.service` to run `docker compose up -d` on boot.

### 2.2 RDS — metadata DB

| Setting | Value | Reason |
|---|---|---|
| Engine | PostgreSQL 16 | matches `sqlalchemy.ext.asyncio` + `asyncpg` stack |
| Instance class | `db.t4g.small` | Burstable ARM, sufficient for metadata workload |
| Storage | 20 GB gp3 with autoscale cap 100 GB | File metadata grows slowly |
| Multi-AZ | Off at launch, flip on after we have revenue | Pay for what we measurably need |
| Backup retention | 7 days | SOC2-friendly floor |

Schema lives in `alembic/versions/`. Deploy runs `alembic upgrade head`
via `deploy/scripts/migrate.sh` **before** rolling the new API
container — never after. See GAP G10 (`docs/MERGE_TRIAGE.md`) for why
`init_db()` must not race Alembic in prod.

### 2.3 Cold storage — Cloudflare R2 (primary) or S3 (fallback)

**Prefer Cloudflare R2.** R2 is S3-API-compatible but charges zero
egress, which matters because our whole business model is "users pull
their own data out on demand" — AWS S3 egress alone would swallow the
storage tier margin.

| Provider | Egress / month | Storage / GB-month | Notes |
|---|---|---|---|
| Cloudflare R2 | **$0** | $0.015 | Primary. Bucket: `windy-cloud-storage` |
| AWS S3 | $0.09 / GB after 100 GB | $0.023 | Fallback only — document why if you flip |

R2 is reached through boto3 with a custom endpoint; see
`api/app/providers/r2.py`. The four vars `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` must all be
set together — partial config is rejected at startup (GAP G4, see
`api/app/config.py:r2_misconfiguration_reason`).

To fall back to S3, comment out the R2 vars and set
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` with `s3:PutObject`,
`s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket` on the bucket only.

### 2.4 GPU compute — RunPod Serverless

Phase 1 compute (Whisper-v3 large, STT) runs on RunPod Serverless:
we pay per billed second of GPU time with no idle cost. Set
`RUNPOD_API_KEY` + `RUNPOD_ENDPOINT_ID`. Markup is controlled by
`STT_MARKUP` (default 3x RunPod cost) and the free-minute allowance
by `STT_FREE_MINUTES`.

SageMaker is the Phase-2 fallback; set `SAGEMAKER_ENDPOINT_NAME` to
enable. Leave unset at launch.

### 2.5 IAM

The Terraform module creates two roles:

- `windy-cloud-api` — attached to the EC2 instance profile.
  Permissions: pull from GHCR (none needed; public), write to
  CloudWatch Logs, read from Secrets Manager for the prod env file.
- `windy-cloud-deploy` — assumed by the GitHub Actions deploy
  workflow. Permissions: `ec2:*` on the tagged instance,
  `ssm:SendCommand` for remote migrate + restart.

Neither role holds the R2, Stripe, or JWKS secrets — those come from
Secrets Manager at container startup via `deploy/scripts/fetch-secrets.sh`
(to be added; tracked in the Grant to-do).

---

## 3. Terraform module

The starter module lives at **`deploy/terraform/`** and is the canonical
source for the resources listed above. The older
`deploy/aws-terraform/` tree is kept only as a reference for the
single-node prototype and will be retired once `deploy/terraform/` is
applied in prod.

```bash
cd deploy/terraform
terraform init
terraform plan -var="ssh_public_key=$(cat ~/.ssh/id_ed25519.pub)" \
               -var="db_password=$(pbpaste)"
terraform apply
```

Outputs include the API EIP, the RDS endpoint, and the IAM role ARNs
— all the values the application and CI need.

---

## 4. Stripe webhook

Stripe sends plan-change and subscription events to
`POST /api/v1/webhooks/stripe` (Wave 9 endpoint — tracked separately).
For Wave 9 launch we only wire the route placeholder + webhook secret
rotation; the business logic ships in Wave 10.

Configuration steps:

1. In the Stripe dashboard, create a webhook endpoint targeting
   `https://cloud.windyfly.ai/api/v1/webhooks/stripe`.
2. Subscribe to: `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.paid`, `invoice.payment_failed`.
3. Copy the signing secret into `STRIPE_WEBHOOK_SECRET`
   (see `.env.production.example`).
4. Rotate quarterly; the rotation is non-breaking — Stripe lets you
   keep two secrets valid simultaneously during cutover.

---

## 5. Cron jobs

### 5.1 Quota-warning emailer

Runs nightly at `07:00 UTC` (~midnight PT). Emails any user whose
storage has crossed 70 %, 90 %, or 100 % of their quota since the
last run. The job is idempotent — it reads
`user_plan_warning_state` so a user who was already warned at 70 %
isn't warned again until they cross a higher threshold.

```cron
0 7 * * * /opt/windy-cloud/scripts/warn-quota.sh >> /var/log/warn-quota.log 2>&1
```

Script is thin: it `docker exec`s into the API container and calls the
internal `/api/v1/admin/quota-warnings/run` endpoint with the service
token. The endpoint itself is a Wave 10 deliverable; the cron line
above is what prod will use once it lands.

### 5.2 Retention cleanup

Already wired as an async startup task
(`api/app/tasks/retention_cleanup.py`). No cron needed; it runs on
lifespan startup and re-runs every 24 h via `asyncio.sleep`.

### 5.3 Billing snapshot

Same deal — wired as an async startup task in
`api/app/tasks/billing_snapshot.py`. Runs daily at 03:00 UTC.

---

## 6. Release cutover checklist

The first time you apply this:

1. `terraform apply` — EC2, RDS, IAM, security groups.
2. Populate Secrets Manager from `.env.production.example`.
3. Run `deploy/scripts/migrate.sh` against the fresh RDS instance.
4. Push a release tag; CI builds the image and pushes to GHCR.
5. SSH into the EC2 host, run `systemctl start windycloud`.
6. `scripts/smoke-test.sh https://cloud.windyfly.ai` — exit 0 required.
7. Flip DNS from the staging EIP to the prod EIP.
8. Tail `/var/log/windycloud.log` for the first hour.

On subsequent deploys the GitHub Actions `deploy.yml` handles steps
3–7. Step 6 is the gate — a non-zero exit rolls the ALB target back
to the previous version automatically.
