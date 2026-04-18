variable "aws_region" {
  description = "AWS region for all resources. Default us-west-2 per DEPLOY.md §1."
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Tag propagated to every resource (prod, staging, dev)."
  type        = string
  default     = "prod"
}

variable "instance_type" {
  description = "EC2 instance type for the API host. t3.medium matches Fargate CI spec."
  type        = string
  default     = "t3.medium"
}

variable "ami_id" {
  description = "Ubuntu 24.04 LTS AMI. Default is the Canonical publisher AMI for us-west-2; override per region."
  type        = string
  default     = "ami-04dd23e62ed049936"
}

variable "domain" {
  description = "Public hostname for the API. Used for Route53 record and TLS."
  type        = string
  default     = "cloud.windyfly.ai"
}

variable "ssh_public_key" {
  description = "SSH public key installed on the API host."
  type        = string
}

variable "bastion_cidr" {
  description = "CIDR allowed to SSH into the API host. Default is the Windy office block; tighten before applying."
  type        = string
  default     = "0.0.0.0/0"
}

variable "db_instance_class" {
  description = "RDS instance class. db.t4g.small is the burstable ARM baseline."
  type        = string
  default     = "db.t4g.small"
}

variable "db_allocated_storage_gb" {
  description = "Initial RDS storage in GB. Autoscales up to db_max_storage_gb."
  type        = number
  default     = 20
}

variable "db_max_storage_gb" {
  description = "RDS storage autoscaling ceiling in GB."
  type        = number
  default     = 100
}

variable "db_password" {
  description = "PostgreSQL master password. Inject via -var or TF_VAR; never commit."
  type        = string
  sensitive   = true
}

variable "r2_bucket_name" {
  description = "Cloudflare R2 bucket used for cold storage. Created out-of-band; referenced only in outputs."
  type        = string
  default     = "windy-cloud-storage"
}

variable "github_repository" {
  description = "OWNER/REPO that the deploy IAM role trusts via OIDC."
  type        = string
  default     = "sneakyfree/WindyCloud"
}
