# Windy Cloud — AWS Production Deployment

This runbook covers the **production AWS target**: API on ECS Fargate,
PostgreSQL on RDS, cold storage on Cloudflare R2, plus the lifecycle +
monitoring configuration needed to ship the per-product archive endpoints
(mail, chat, word, clone, agent) safely.

Scope of this doc:
- [1. Architecture overview](#1-architecture-overview)
- [2. Prerequisites](#2-prerequisites)
- [3. Cloudflare R2 bucket + S3-compatible credentials](#3-cloudflare-r2)
- [4. PostgreSQL via RDS](#4-postgresql-via-rds)
- [5. API on ECS Fargate](#5-api-on-ecs-fargate)
- [6. Lifecycle policies (90-day hot → R2 cold)](#6-lifecycle-policies)
- [7. Per-product archive endpoints](#7-per-product-archive-endpoints)
- [8. Monitoring + alerting](#8-monitoring)
- [9. First-boot checklist](#9-first-boot-checklist)

For shared secrets (SERVICE_TOKEN, IDENTITY_WEBHOOK_SECRET, etc.) see
`deploy/docs/env-vars.md`. That doc is the single source of truth for env
vars; this doc only references them.

---

## 1. Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         AWS account                              │
│                                                                  │
│  ┌────────────┐   ┌────────────┐   ┌─────────────────────┐      │
│  │   Route53  │──▶│    ALB     │──▶│  ECS Fargate         │      │
│  │   TLS term │   │  :443      │   │  (windy-cloud x N)   │      │
│  └────────────┘   └────────────┘   └──────────┬──────────┘      │
│                                               │                  │
│                           ┌───────────────────┼──────────────┐   │
│                           │                   │              │   │
│                           ▼                   ▼              ▼   │
│                   ┌─────────────┐   ┌──────────────┐  ┌────────┐ │
│                   │    RDS      │   │  Secrets     │  │  SQS   │ │
│                   │ PostgreSQL  │   │  Manager     │  │(future)│ │
│                   │   16        │   │  (env vars)  │  └────────┘ │
│                   └─────────────┘   └──────────────┘             │
│                                                                  │
└──────────────────────────────────────────┬──────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────┐
                    │                                          │
                    ▼                                          ▼
          ┌─────────────────┐                     ┌──────────────────┐
          │  Cloudflare R2  │                     │    Eternitas     │
          │ (hot+cold blobs)│                     │ /api/v1/trust/*  │
          └─────────────────┘                     └──────────────────┘
```

Why R2 instead of S3 for storage:
- Zero egress cost to browsers (cold-storage restore is free).
- S3-API compatible, so `boto3` just works.
- We keep RDS in AWS so the cloud gateway + DB are in the same VPC for low
  latency and in-VPC auth.

---

## 2. Prerequisites

You need:
- AWS account with permissions for: ECS, ECR, RDS, ALB, Route53, IAM, CloudWatch, Secrets Manager.
- A Cloudflare account with R2 enabled.
- The domain `cloud.windycloud.com` (or your environment's equivalent) delegated to Route53 or routed through a CNAME.
- `aws` CLI ≥ 2.15, `terraform` ≥ 1.6 (existing module lives at `deploy/aws-terraform/`).
- `docker` + buildx for multi-arch image builds (Fargate is `linux/amd64`).

---

## 3. Cloudflare R2

### 3.1 Create the bucket

```
1. Cloudflare dashboard → R2 → Create bucket
   Name:        windy-cloud-storage-prod
   Location:    Automatic
   Encryption:  Enabled (Cloudflare-managed keys)
2. Click the bucket → Settings → Public access = OFF (all access via signed URLs).
```

### 3.2 Mint S3-compatible API credentials

```
R2 → Manage R2 API Tokens → Create API Token
  Permissions:  Object Read & Write
  Bucket scope: windy-cloud-storage-prod
  TTL:          No expiry (rotate yearly, see §8.3)
```

Copy the four values into AWS Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name /prod/windy-cloud/r2 \
  --secret-string '{
    "R2_ACCOUNT_ID":        "<from cloudflare>",
    "R2_ACCESS_KEY_ID":     "<token access key>",
    "R2_SECRET_ACCESS_KEY": "<token secret>",
    "R2_BUCKET":            "windy-cloud-storage-prod",
    "R2_ENDPOINT":          "https://<account>.r2.cloudflarestorage.com"
  }'
```

ECS task-definition `secrets` block pulls each key as an env var. Never put
R2 creds in a task-definition `environment` block — they'd appear in
`aws ecs describe-task-definition` output to any IAM principal with that
permission.

### 3.3 Verify from the cloud API

```bash
# Inside the running container:
curl -fsS http://localhost:8200/api/v1/storage/health
# → {"status":"ok","provider":"R2StorageProvider"}
```

If the provider is `LocalDiskProvider`, one of the four R2_* env vars is
missing or typoed. Check CloudWatch logs, not the response body.

---

## 4. PostgreSQL via RDS

### 4.1 Instance sizing

| Env | Instance | Storage | Multi-AZ | Backup retention |
|---|---|---|---|---|
| staging | `db.t4g.micro` | 20 GB gp3 | No | 3 days |
| prod (launch) | `db.t4g.small` | 50 GB gp3 | **Yes** | 14 days |
| prod (scale) | `db.t4g.medium`+ | 100 GB gp3 | Yes | 14 days |

Parameter group: start with the default `postgres16` group. Only tune if
`pg_stat_statements` shows a specific problem; don't pre-optimise.

### 4.2 Create

```bash
aws rds create-db-instance \
  --db-instance-identifier windy-cloud-prod \
  --engine postgres --engine-version 16.4 \
  --db-instance-class db.t4g.small \
  --allocated-storage 50 --storage-type gp3 \
  --master-username windy \
  --master-user-password "$(openssl rand -base64 32)" \
  --vpc-security-group-ids sg-<private-db-only> \
  --db-subnet-group-name windy-private \
  --backup-retention-period 14 \
  --multi-az \
  --storage-encrypted \
  --deletion-protection
```

Security group: **only** allow inbound 5432 from the ECS service SG. Never
make the RDS instance publicly reachable.

### 4.3 Migrations

Fargate task for one-shot `alembic upgrade head`:

```bash
aws ecs run-task \
  --cluster windy-cloud-prod \
  --task-definition windy-cloud-migrate:latest \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-cloud-api],assignPublicIp=DISABLED}"
```

The migration task image is the same as the API image; override `command`
to `uv run alembic upgrade head`. Run it once per release **before** the
API task set rolls to the new image — the idempotent migrations at
`alembic/versions/002_*.py` and `003_*.py` are safe on both fresh DBs and
existing ones.

### 4.4 Secret wiring

```bash
aws secretsmanager create-secret \
  --name /prod/windy-cloud/db \
  --secret-string '{
    "DATABASE_URL": "postgresql+asyncpg://windy:<password>@<rds-host>:5432/windy_cloud"
  }'
```

---

## 5. API on ECS Fargate

### 5.1 Build + push image

```bash
# On a build host (linux/amd64)
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

docker buildx build --platform linux/amd64 \
  -t <account>.dkr.ecr.us-east-1.amazonaws.com/windy-cloud:$(git rev-parse --short HEAD) \
  --push .
```

### 5.2 Task sizing vs `max_upload_size`

**Invariant:** `max_upload_size` must be substantially smaller than task
memory. The app ships a 256 MB default against the 1024 MB Fargate task
size below; a single legit max-sized upload then peaks at ~256 MB of
Python bytes plus the spooled multipart buffer, well inside the headroom.

If you bump task memory, you can bump `MAX_UPLOAD_SIZE` — but keep a 4×
ratio minimum (memory ≥ 4 × max_upload_size) so concurrent uploads and
the retention-cleanup background task don't starve each other.

ALB / WAF should enforce the same ceiling at the edge via
`client_max_body_size` (nginx sidecar) or a WAF body-size rule so
traffic never reaches the pod if it's going to be rejected anyway.

### 5.3 Task definition skeleton

```json
{
  "family": "windy-cloud-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
  "executionRoleArn": "arn:aws:iam::<account>:role/windyCloudExec",
  "taskRoleArn":      "arn:aws:iam::<account>:role/windyCloudTask",
  "containerDefinitions": [{
    "name": "api",
    "image": "<account>.dkr.ecr.us-east-1.amazonaws.com/windy-cloud:<sha>",
    "portMappings": [{"containerPort": 8200, "protocol": "tcp"}],
    "environment": [
      {"name": "WINDY_PRO_JWKS_URL",   "value": "https://windyword.ai/.well-known/jwks.json"},
      {"name": "ETERNITAS_JWKS_URL",   "value": "https://api.eternitas.ai/.well-known/eternitas-keys"},
      {"name": "ETERNITAS_URL",        "value": "https://api.eternitas.ai"},
      {"name": "ETERNITAS_USE_MOCK",   "value": "false"},
      {"name": "PRICING_URL",          "value": "https://windyword.ai/pricing"},
      {"name": "CORS_ORIGINS",         "value": "https://windyword.ai,https://windycloud.com"}
    ],
    "secrets": [
      {"name": "DATABASE_URL",            "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/db:DATABASE_URL::"},
      {"name": "R2_ACCOUNT_ID",           "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/r2:R2_ACCOUNT_ID::"},
      {"name": "R2_ACCESS_KEY_ID",        "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/r2:R2_ACCESS_KEY_ID::"},
      {"name": "R2_SECRET_ACCESS_KEY",    "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/r2:R2_SECRET_ACCESS_KEY::"},
      {"name": "R2_BUCKET",               "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/r2:R2_BUCKET::"},
      {"name": "R2_ENDPOINT",             "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/r2:R2_ENDPOINT::"},
      {"name": "IDENTITY_WEBHOOK_SECRET", "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/shared:IDENTITY_WEBHOOK_SECRET::"},
      {"name": "ETERNITAS_WEBHOOK_SECRET","valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/shared:ETERNITAS_WEBHOOK_SECRET::"},
      {"name": "SERVICE_TOKEN",           "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/shared:SERVICE_TOKEN::"},
      {"name": "SENTRY_DSN",              "valueFrom": "arn:aws:secretsmanager:...:/prod/windy-cloud/observability:SENTRY_DSN::"}
    ],
    "healthCheck": {
      "command": ["CMD-SHELL", "curl -fsS http://localhost:8200/health || exit 1"],
      "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 15
    },
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group":         "/ecs/windy-cloud",
        "awslogs-region":        "us-east-1",
        "awslogs-stream-prefix": "api"
      }
    }
  }]
}
```

### 5.4 Service + autoscaling

```bash
aws ecs create-service \
  --cluster windy-cloud-prod \
  --service-name windy-cloud-api \
  --task-definition windy-cloud-api:1 \
  --desired-count 2 \
  --launch-type FARGATE \
  --deployment-configuration minimumHealthyPercent=100,maximumPercent=200 \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIV_SUBNETS],securityGroups=[$SG_CLOUD_API],assignPublicIp=DISABLED}" \
  --load-balancers targetGroupArn=$TG_ARN,containerName=api,containerPort=8200 \
  --health-check-grace-period-seconds 60
```

Autoscale on ALB request count (simpler than CPU for this workload):

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/windy-cloud-prod/windy-cloud-api \
  --min-capacity 2 --max-capacity 10
aws application-autoscaling put-scaling-policy \
  --policy-name rps-scaler \
  --service-namespace ecs --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/windy-cloud-prod/windy-cloud-api \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 200,
    "PredefinedMetricSpecification": {
      "PredefinedMetricType": "ALBRequestCountPerTarget",
      "ResourceLabel": "app/windy-cloud-alb/xxx/targetgroup/windy-cloud-tg/yyy"
    }
  }'
```

### 5.5 ALB + TLS + WAF

- Target group health check: `GET /health`, 200, interval 30s, threshold 2.
- Listener rules:
  - `Host: cloud.windycloud.com` → forward to `windy-cloud-tg`.
  - Default `/*` → return fixed 404 to discourage direct ALB lookups.
- ACM cert in `us-east-1` (ALB requires in-region certs).
- WAF: attach `AWSManagedRulesCommonRuleSet` + a rate-limit rule at
  1000 req / 5 min / IP. Webhook endpoints (`/api/v1/webhooks/*`) are
  exempted from the rate-limit rule because Eternitas retries use the
  same source IP.

---

## 6. Lifecycle policies

### 6.1 The 90-day hot → R2 cold pipeline

**Data model:** every uploaded blob is stored immediately in R2 under
`{windy_identity_id}/{product}/{type}/{filename}` and a `FileRecord` row
is written to Postgres with `retention_count` and `retention_days`
metadata. There is **no "hot" disk tier** in production — R2 is the only
blob store. The lifecycle is implemented by moving old objects from the
default R2 storage class to `Infrequent Access` inside the same bucket,
which is cheaper per GB-month but adds retrieval latency.

### 6.2 R2 bucket lifecycle rules

R2 supports lifecycle rules via the S3-compatible API:

```bash
aws s3api put-bucket-lifecycle-configuration \
  --endpoint-url https://<account>.r2.cloudflarestorage.com \
  --bucket windy-cloud-storage-prod \
  --lifecycle-configuration file://r2-lifecycle.json
```

`r2-lifecycle.json`:

```json
{
  "Rules": [
    {
      "ID": "archives-hot-to-ia-90d",
      "Status": "Enabled",
      "Filter": {"Prefix": ""},
      "Transitions": [
        {"Days": 90, "StorageClass": "STANDARD_IA"}
      ]
    },
    {
      "ID": "explicit-cold-never-delete",
      "Status": "Enabled",
      "Filter": {"Prefix": ""},
      "NoncurrentVersionExpiration": {"NoncurrentDays": 365}
    }
  ]
}
```

### 6.3 Retention enforcement inside the app

`api/app/tasks/retention_cleanup.py` runs at container startup and nightly
via a CloudWatch-Events-triggered one-shot Fargate task. It honours
the `retention_count` and `retention_days` fields that products set
when they call `POST /api/v1/archive/{product}`.

Nightly schedule:

```bash
aws events put-rule --name windy-cloud-nightly-cleanup \
  --schedule-expression "cron(5 3 * * ? *)"  # 03:05 UTC

aws events put-targets --rule windy-cloud-nightly-cleanup --targets '[{
  "Id": "1",
  "Arn": "arn:aws:ecs:us-east-1:<account>:cluster/windy-cloud-prod",
  "RoleArn": "arn:aws:iam::<account>:role/ecsEventsRole",
  "EcsParameters": {
    "TaskDefinitionArn": "arn:aws:ecs:...:task-definition/windy-cloud-cleanup",
    "LaunchType": "FARGATE",
    "NetworkConfiguration": { ... }
  }
}]'
```

The cleanup task is the same image with command overridden to
`uv run python -m api.app.tasks.retention_cleanup --once`.

### 6.4 Product-specific retention (set at upload time)

Products declare retention in the `metadata` form field:

```
POST /api/v1/archive/chat
  metadata = {"encrypted": true, "retention_count": 7}          # keep 7 newest
POST /api/v1/archive/mail
  metadata = {"retention_days": 90}                              # cut off at 90d
POST /api/v1/archive/recordings
  metadata = {"retention_days": 365}                             # year-long hold
```

`retention_count` beats `retention_days` when both are set.

---

## 7. Per-product archive endpoints

All five product backends push archives to Cloud. They may authenticate
with **either** the end-user's JWT **or** a service token (per Wave 2,
`routes/archive.py`). Service callers must pass
`X-Service-Token: $SERVICE_TOKEN` + a form field `windy_identity_id`.

| Caller | Endpoint | Default metadata | Notes |
|---|---|---|---|
| windy-mail | `POST /api/v1/archive/mail` | `{"retention_days": 90}` | Mail server nightly pg_dump, one blob per dump |
| windy-chat | `POST /api/v1/archive/chat` | `{"encrypted": true, "retention_count": 7}` | E2EE blob; Cloud never sees plaintext |
| windy-word (pro) | `POST /api/v1/archive/recordings` | `{}` | Raw audio blobs; consult retention via user's plan |
| windy-clone | `POST /api/v1/archive/agent` | `{}` | Agent DB + voice prints |
| windy-agent | `POST /api/v1/archive/agent` | `{}` | Agent session state |
| windy-code | `POST /api/v1/archive/code-settings` | `{}` | IDE settings.json sync |

Per-product gotchas:
- **Chat** payloads are already encrypted by the product; Cloud stores the
  ciphertext verbatim. The storage bucket does **not** need per-object
  SSE-C on top.
- **Recordings** are large (50 MB+ typical). The `max_upload_size` setting
  defaults to 1 GB; do not raise it without tightening WAF body-size limits.
- **Mail** dumps are often gzipped already; don't re-compress at the
  provider layer.

### 7.1 Integration test per product

Every product's CI should include a push against the staging Cloud:

```bash
curl -fsS -X POST https://staging-cloud.windycloud.com/api/v1/archive/chat \
  -H "X-Service-Token: $STAGING_SERVICE_TOKEN" \
  -F "file=@./fixture.enc" \
  -F "windy_identity_id=test-product-$PRODUCT_CI_ID" \
  -F 'metadata={"encrypted":true,"retention_count":3}'
```

Expected response:

```json
{"file_id": "...", "key": "test-product-.../windy_chat/chat_backup/...", "product": "windy_chat", "type": "chat_backup", "size": N}
```

---

## 8. Monitoring

### 8.1 CloudWatch Alarms

Create these at minimum. Every alarm routes to the `#cloud-alerts`
channel via SNS → Chatbot.

```yaml
# 1. ECS service unhealthy
- name: CloudApiRunningTasksBelowTarget
  metric: ECS/ClusterName=windy-cloud-prod,ServiceName=windy-cloud-api/RunningTaskCount
  statistic: Average
  threshold: "< desired_count * 0.5 for 2 datapoints"
  period: 60s

# 2. 5xx rate
- name: CloudApi5xxRate
  metric: ApplicationELB/TargetGroup=windy-cloud-tg/HTTPCode_Target_5XX_Count
  statistic: Sum
  threshold: "> 20 per minute for 5 minutes"
  period: 60s

# 3. DB connections
- name: CloudDbConnectionsHigh
  metric: RDS/DBInstanceIdentifier=windy-cloud-prod/DatabaseConnections
  statistic: Average
  threshold: "> 80% of max for 10 minutes"

# 4. RDS disk free
- name: CloudDbStorageLow
  metric: RDS/DBInstanceIdentifier=windy-cloud-prod/FreeStorageSpace
  threshold: "< 5 GiB"

# 5. R2 request errors (custom metric, emitted from app)
- name: R2UploadFailureRate
  metric: WindyCloud/R2UploadErrors
  threshold: "> 5% over 10 minutes"
```

### 8.2 Business-metric alarms (more important than infra alarms)

Ship these as app-emitted metrics. They catch bugs the infra layer never sees.

```yaml
# 6. Archive job failures per product (any spike = product regression)
- name: ArchiveJobFailuresByProduct
  metric: WindyCloud/ArchiveFailures{product=*}
  threshold: "any product > 10 failures / 5 min"

# 7. Quota exceeded rate (indicates tier/multiplier misconfiguration)
- name: QuotaExceededRate
  metric: WindyCloud/QuotaExceeded507
  threshold: "> 50 per hour (normal baseline ~5)"

# 8. Trust API upstream health (warns if Eternitas degrades)
- name: TrustApiUpstreamErrorRate
  metric: WindyCloud/TrustApiErrors
  threshold: "> 5% over 10 minutes"

# 9. Frozen-account rejections (spike may indicate revocation storm)
- name: FrozenAccountRejections
  metric: WindyCloud/FrozenAccount403
  threshold: "> 20 per 5 min"
```

The current codebase exposes some of these via `logger.info/warning` lines
— the next step is to promote them to CloudWatch Embedded Metrics Format
(EMF) so the `WindyCloud/*` namespace populates. Tracked in
`DNA_STRAND_MASTER_PLAN.md`; not a launch blocker.

### 8.3 Credential rotation schedule

| Secret | Cadence | How |
|---|---|---|
| R2 API token | Annual | New token at Cloudflare, update secret, roll ECS tasks, revoke old token |
| RDS master password | Annual | `aws rds modify-db-instance --master-user-password`, then update secret, then roll API |
| IDENTITY_WEBHOOK_SECRET | Quarterly | Coordinate with windy-pro |
| ETERNITAS_WEBHOOK_SECRET | Quarterly | Coordinate with eternitas platform registration |
| SERVICE_TOKEN | Quarterly | Roll across all 6 product services in one maintenance window |

Automate with a CloudWatch Events rule firing to a Lambda that opens a
GitHub issue on the windy-cloud repo 14 days before the next expected
rotation — don't rely on humans remembering.

---

## 9. First-boot checklist

Cut this and work through it on launch day:

- [ ] R2 bucket `windy-cloud-storage-prod` exists, public access off
- [ ] R2 API token minted, stored in `/prod/windy-cloud/r2`
- [ ] RDS instance `windy-cloud-prod` healthy, Multi-AZ, backups 14d, deletion protection on
- [ ] `/prod/windy-cloud/db` holds a working `DATABASE_URL`
- [ ] `/prod/windy-cloud/shared` holds IDENTITY_WEBHOOK_SECRET, ETERNITAS_WEBHOOK_SECRET, SERVICE_TOKEN (all minted per `deploy/docs/env-vars.md`)
- [ ] ECR repo `windy-cloud` exists; at least one tagged image pushed
- [ ] Fargate cluster `windy-cloud-prod` + task role + execution role created
- [ ] Run the migration task (`alembic upgrade head`) — confirms DB connectivity before the API task rolls
- [ ] ECS service `windy-cloud-api` running `desired_count=2` with healthy targets on the ALB
- [ ] ALB hostname `cloud.windycloud.com` returns 200 on `GET /health`
- [ ] `GET /api/v1/storage/health` reports `provider=R2StorageProvider`
- [ ] `curl -H "X-Service-Token: $TOKEN" $URL/api/v1/identity/by-passport/ET26-TEST-FAIR` returns 404 (not 401) — proves token is wired
- [ ] Windy Pro registered as a platform on Eternitas so `passport.*` webhooks dispatch
- [ ] Cloud subscribed to Eternitas trust.changed stream (`POST /api/v1/platforms/subscriptions` on eternitas)
- [ ] CloudWatch alarms §8.1 in `OK` state
- [ ] Sentry `windy-cloud@<version>` events visible in the prod project
- [ ] Nightly cleanup task scheduled
- [ ] R2 lifecycle policy applied (`aws s3api get-bucket-lifecycle-configuration --bucket ...` returns the rules)
- [ ] CloudWatch log group `/ecs/windy-cloud` retention set (default is forever — we want 30d)
- [ ] Runbook for the "retention deleted the wrong thing" incident pinned in `#cloud-oncall`

Once every box is ticked: flip the Route53 CNAME from staging to prod and
announce in `#windy-launches`.
