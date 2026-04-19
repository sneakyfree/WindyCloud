# Wave 13 Phase 3 — Windy Cloud production deploy runbook

**Scope:** the exact sequence Grant runs to take `wave13/phase3-aws-deploy`
live against the TheWindstorm AWS account (`819439781125`), region
`us-east-1`. Everything below assumes the PR attached to this branch is
merged first.

**Status at branch-point (2026-04-19):**

- Pre-deploy code changes landed (JWKS URLs, Terraform IAM stanza, tfvars template, this doc).
- **No AWS resources were created.** `terraform apply` was *not* run from the agent — that's step 4 below, owned by Grant.
- **DNS decision deferred** (see §6).

---

## Blockers (must clear before Step 3)

| # | Blocker | Proof as of branch-point |
|---|---|---|
| 1 | Phase 1 (`api.windyword.ai`) must be live. Cloud's JWT validator fetches its JWKS on every request. | `curl -I https://api.windyword.ai/.well-known/jwks.json` → **522** (origin unreachable) |
| 2 | Phase 2 (`api.eternitas.ai`) must be live. Same reason, plus the passport-revoked signed-JWT validator. | `curl -I https://api.eternitas.ai/.well-known/eternitas-keys` → **404** |
| 3 | `aws` CLI must be installed + authenticated with the `windy-ecosystem-admin` access key (`AKIA35STKYUC2WRDQGET` — full key in `~/kit-army-config/ACCESS_LOCKBOX.md` §10). | Dev machine: `aws` not installed; `~/.aws/credentials` does not exist. |
| 4 | DNS choice: `api.windycloud.com` on GoDaddy — see §6. | Pending Grant's decision. |

Until all four clear, running `terraform apply` will either fail (3)
or produce an API that 401s every request (1, 2). Don't apply early.

---

## Step 1 — Pre-apply sanity (local)

```bash
cd deploy/terraform
terraform fmt -check
terraform init -backend=false
terraform validate
```

Expected: all three green. These are the checks the Wave 9 smoke
baseline passed; the Phase 3 IAM stanza added here doesn't change the
result.

---

## Step 2 — Fill secrets (local)

```bash
cp deploy/terraform/prod.tfvars.example deploy/terraform/prod.tfvars
# Edit prod.tfvars — uncomment and fill in ssh_public_key + db_password.
```

`ssh_public_key` comes from `~/windy-prod-key.pem` (already on the
deploy machine — see `ls -la ~/windy-prod-key.pem`; run
`ssh-keygen -y -f ~/windy-prod-key.pem` for the matching public key).

`db_password` — mint fresh: `openssl rand -base64 32`. Paste into
`prod.tfvars` *or* pass inline (`-var="db_password=$(...)"`). **Never
commit** `prod.tfvars`.

---

## Step 3 — `terraform apply` (AWS creds required)

```bash
export AWS_PROFILE=windy-ecosystem-admin   # after configuring ~/.aws/credentials
export AWS_REGION=us-east-1

cd deploy/terraform
terraform plan -var-file=prod.tfvars -out=phase3.plan
# Read every resource in the plan output. There should be no unexpected
# creates — the module provisions: 1 EC2 + EIP, 1 RDS instance, 2 SGs,
# 1 subnet group, 2 IAM roles + 3 policies + 1 instance profile.

terraform apply phase3.plan
```

**Expected outputs:**
```
api_public_ip              = "x.x.x.x"            # DNS step needs this
rds_endpoint               = "windy-cloud.xxxx.rds.amazonaws.com"
deploy_role_arn            = "arn:aws:iam::819439781125:role/windy-cloud-deploy"
api_instance_profile_name  = "windy-cloud-api"
```

Copy `api_public_ip` — §6 pastes it into DNS.

### Caveat — the Wave 9 module provisions its own VPC

This module *currently* creates a fresh VPC with SGs and subnets. The
Phase 3 playbook wants Cloud to live in the *shared* TheWindstorm VPC
(`vpc-011cc35a43403f9ef`) alongside Phase 1/2. Two paths:

- **Option A (fast, isolated):** accept the fresh VPC. Cloud runs
  in its own network, independent of Phase 1/2. Works, but cross-
  service traffic (e.g. Cloud calling `api.windyword.ai` for JWKS)
  leaves AWS → DNS → AWS instead of staying inside the VPC. Fine for
  Phase 3, may want to collapse later.
- **Option B (match playbook):** refactor `network.tf` to consume the
  existing VPC / subnets / SGs via `data` blocks before apply. The
  IDs are in `prod.tfvars.example`. Roughly a half-day's work;
  deferred out of Phase 3 scope, tracked as the TODO comment in
  `prod.tfvars.example`.

Ship Option A for Phase 3. Flip to B in Wave 14.

---

## Step 4 — Run the migration on the new RDS

```bash
ssh -i ~/windy-prod-key.pem ubuntu@<api_public_ip>
cd /opt/windy-cloud
docker compose run --rm cloud uv run alembic upgrade head
```

Alembic versions in this branch: `001` → `005`. `005` adds the Stripe
billing columns and `webhook_deliveries` table.

---

## Step 5 — Populate Secrets Manager

Cloud reads runtime secrets from `windy-cloud/*` in Secrets Manager at
container start. IAM already grants the instance profile
`secretsmanager:GetSecretValue` on that prefix.

```bash
./scripts/seed-prod-secrets.sh            # hypothetical — mirror what exists
# or — one secret at a time:
aws secretsmanager create-secret --region us-east-1 \
  --name windy-cloud/identity_webhook_secret \
  --secret-string "$(openssl rand -hex 32)"
aws secretsmanager create-secret --region us-east-1 \
  --name windy-cloud/service_token \
  --secret-string "$(openssl rand -base64 48 | tr -d '=')"
aws secretsmanager create-secret --region us-east-1 \
  --name windy-cloud/r2_access_key_id \
  --secret-string "<from Cloudflare dashboard>"
# ... etc for every CHANGEME in .env.production.example
```

Once the secrets are seeded, restart the container so it picks them up.

---

## Step 6 — DNS: `api.windycloud.com` → `<api_public_ip>`

**`windycloud.com` is on GoDaddy, not Cloudflare.** The Cloudflare DNS
token in the playbook context won't work for this record. Two forks:

### Option A — Manual GoDaddy A record (fastest)

Grant logs into GoDaddy → DNS Management for `windycloud.com` → Add
Record:

- Type: `A`
- Name: `api`
- Value: `<api_public_ip>` from Step 3 output
- TTL: 600 seconds

Document the IP in this runbook under §"Deploy log" when done.

### Option B — Migrate DNS to Cloudflare first

Update GoDaddy's nameservers to Cloudflare's
(`xxx.ns.cloudflare.com` + `yyy.ns.cloudflare.com`), wait for
propagation (up to 48 h), then use the Cloudflare API + token from
the playbook to add the A record. This unlocks Cloudflare's CDN /
WAF / cache — but it's a delay that blocks the rest of Phase 3.

**Recommendation:** A for Phase 3. Queue B as a Wave 14 item — it
improves every subsequent deploy but doesn't block launch.

---

## Step 7 — Certbot

After DNS propagates (check via `dig +short api.windycloud.com` — must
return the EIP):

```bash
ssh -i ~/windy-prod-key.pem ubuntu@<api_public_ip>
sudo certbot --nginx -d api.windycloud.com -m grantwhitmer3@gmail.com --agree-tos --non-interactive
```

---

## Step 8 — Smoke tests

From the deploy machine (not the host):

```bash
cd ~/windy-cloud
SERVICE_TOKEN=<from Secrets Manager> \
USER_JWT=<a Windy-Pro-signed test token> \
./scripts/smoke-test.sh https://api.windycloud.com
```

Additional Phase-3-specific probes the Wave 9 smoke script doesn't
cover:

```bash
# 1. /webhooks/stripe rejects an unsigned request
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST https://api.windycloud.com/api/v1/webhooks/stripe \
  -H "Content-Type: application/json" -d '{}'
# Expected: 400

# 2. /webhooks/passport/revoked rejects garbage JWT
curl -s -o body.json -w "%{http_code}\n" \
  -X POST https://api.windycloud.com/api/v1/webhooks/passport/revoked \
  -H "Content-Type: application/json" \
  -d '{"token":"not.a.jwt"}'
# Expected: 403

# 3. Dual JWKS reachability (ignore-signature probe — just confirms fetch works)
aws ec2 ssm get-command-invocation ...   # or SSH + curl internally:
# curl https://api.windyword.ai/.well-known/jwks.json → 200
# curl https://api.eternitas.ai/.well-known/eternitas-keys → 200
```

All three must pass before calling Phase 3 live.

---

## Step 9 — Hand off to Phase 4

Once the smoke passes, update
`~/wave13-deploy-prompts.md` with the resolved values:

- API EIP: `...`
- RDS endpoint: `...`
- DNS: confirmed via `dig`
- Deployed at: `<date> <time> UTC`

Phase 4 (`windy-chat`) consumes:
- `api.windycloud.com` (storage API)
- Same shared VPC / SGs if Option B was taken; its own otherwise.

---

## Deploy log

_Fill in at apply time — keeps a permanent record of the prod values
even if Terraform state moves._

- `terraform apply` at: `_____ UTC`
- EIP: `_____`
- RDS endpoint: `_____`
- DNS choice: `A` (GoDaddy manual) | `B` (migrated to Cloudflare on `____`)
- Certbot cert expires: `_____`
- First smoke-test pass at: `_____ UTC`
