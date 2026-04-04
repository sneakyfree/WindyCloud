output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.windy_cloud.id
}

output "elastic_ip" {
  description = "Elastic IP address"
  value       = aws_eip.windy_cloud.public_ip
}

output "ssh_command" {
  description = "SSH into the instance"
  value       = "ssh -i windy-cloud-key.pem ubuntu@${aws_eip.windy_cloud.public_ip}"
}

output "health_url" {
  description = "Health check endpoint"
  value       = "https://${var.domain}/health"
}

output "api_url" {
  description = "API base URL"
  value       = "https://${var.domain}/api/v1"
}
