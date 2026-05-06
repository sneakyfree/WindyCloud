variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type for Windy Cloud API"
  type        = string
  default     = "t3.medium"
}

variable "ami_id" {
  description = "Ubuntu 24.04 AMI ID (region-specific)"
  type        = string
  default     = "ami-0c7217cdde317cfec" # Ubuntu 24.04 us-east-1
}

variable "domain" {
  description = "Domain for Windy Cloud"
  type        = string
  default     = "cloud.windycloud.com"
}

variable "ssh_public_key" {
  description = "SSH public key for EC2 access"
  type        = string
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID (optional — leave empty to skip DNS)"
  type        = string
  default     = ""
}
