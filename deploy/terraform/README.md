# Windy Cloud — Starter Terraform module

Creates the AWS resources described in `DEPLOY.md` section 2:

- EC2 `t3.medium` API host (Ubuntu 24.04 LTS, encrypted 30 GB gp3)
- Elastic IP + security group (80 / 443 public, 22 restricted)
- RDS PostgreSQL 16 (`db.t4g.small`, 20 GB gp3, 7-day backups)
- IAM roles: `windy-cloud-api` (instance profile) and
  `windy-cloud-deploy` (assumed by GitHub Actions)
- Local state reference to a Cloudflare R2 bucket (R2 has no AWS
  Terraform resource; the bucket is created via
  `scripts/r2-bucket-create.sh` and exposed here as a data block so
  the IAM and env output stay wired)

## Relationship to `deploy/aws-terraform/`

`deploy/aws-terraform/` is the older single-node prototype kept in
tree for reference. New work goes in `deploy/terraform/`; prod is
expected to be applied from here.

## Usage

```bash
cd deploy/terraform
terraform init
terraform plan \
  -var="ssh_public_key=$(cat ~/.ssh/id_ed25519.pub)" \
  -var="db_password=$(openssl rand -base64 32)"
terraform apply
```

Outputs:

- `api_public_ip` — point your DNS A record here
- `rds_endpoint` — use for `DATABASE_URL` in Secrets Manager
- `deploy_role_arn` — paste into GitHub Actions secrets as
  `AWS_DEPLOY_ROLE_ARN`
- `api_instance_profile_name` — referenced by CloudWatch agent config

## Remote state

State is local by default to keep the first apply simple. Flip to an
S3 backend before handing the module to a second operator:

```hcl
terraform {
  backend "s3" {
    bucket = "windy-cloud-tfstate"
    key    = "prod/terraform.tfstate"
    region = "us-west-2"
  }
}
```
