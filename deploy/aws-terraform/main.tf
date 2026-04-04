terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.5"
}

provider "aws" {
  region = var.aws_region
}

# --- Security Group ---
resource "aws_security_group" "windy_cloud" {
  name        = "windy-cloud-sg"
  description = "Windy Cloud API server"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Windy Cloud API"
    from_port   = 8200
    to_port     = 8200
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "windy-cloud"
    Project = "windy-cloud"
  }
}

# --- SSH Key ---
resource "aws_key_pair" "windy_cloud" {
  key_name   = "windy-cloud-key"
  public_key = var.ssh_public_key
}

# --- EC2 Instance ---
resource "aws_instance" "windy_cloud" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.windy_cloud.key_name
  vpc_security_group_ids = [aws_security_group.windy_cloud.id]

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = <<-USERDATA
    #!/bin/bash
    export WINDY_CLOUD_DOMAIN="${var.domain}"
    curl -fsSL https://raw.githubusercontent.com/sneakyfree/WindyCloud/main/deploy/aws-setup.sh | bash
  USERDATA

  tags = {
    Name    = "windy-cloud"
    Project = "windy-cloud"
  }
}

# --- Elastic IP ---
resource "aws_eip" "windy_cloud" {
  instance = aws_instance.windy_cloud.id
  domain   = "vpc"

  tags = {
    Name    = "windy-cloud-eip"
    Project = "windy-cloud"
  }
}

# --- Route53 DNS (optional — requires hosted zone) ---
data "aws_route53_zone" "main" {
  count = var.route53_zone_id != "" ? 1 : 0
  zone_id = var.route53_zone_id
}

resource "aws_route53_record" "windy_cloud" {
  count   = var.route53_zone_id != "" ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = var.domain
  type    = "A"
  ttl     = 300
  records = [aws_eip.windy_cloud.public_ip]
}
