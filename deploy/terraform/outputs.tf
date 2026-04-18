output "api_public_ip" {
  description = "Elastic IP for the API host — point your DNS A record here."
  value       = aws_eip.api.public_ip
}

output "api_instance_id" {
  description = "EC2 instance ID — used by SSM deploy commands."
  value       = aws_instance.api.id
}

output "api_instance_profile_name" {
  description = "Instance profile name — referenced by CloudWatch agent config."
  value       = aws_iam_instance_profile.api.name
}

output "rds_endpoint" {
  description = "Postgres endpoint for DATABASE_URL."
  value       = aws_db_instance.main.endpoint
  sensitive   = true
}

output "deploy_role_arn" {
  description = "GitHub Actions deploy role — set as AWS_DEPLOY_ROLE_ARN in repo secrets."
  value       = aws_iam_role.deploy.arn
}

output "r2_bucket_name" {
  description = "Cloudflare R2 bucket used by R2_BUCKET. Created out-of-band; surfaced here for reference."
  value       = var.r2_bucket_name
}
