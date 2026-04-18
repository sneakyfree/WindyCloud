resource "aws_key_pair" "api" {
  key_name   = "windy-cloud-api"
  public_key = var.ssh_public_key
}

resource "aws_instance" "api" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.api.key_name
  vpc_security_group_ids = [aws_security_group.api.id]
  iam_instance_profile   = aws_iam_instance_profile.api.name
  subnet_id              = data.aws_subnets.default.ids[0]

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    http_endpoint               = "enabled"
  }

  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  user_data = <<-USERDATA
    #!/bin/bash
    set -euo pipefail
    export WINDY_CLOUD_DOMAIN="${var.domain}"
    curl -fsSL https://raw.githubusercontent.com/${var.github_repository}/main/deploy/aws-setup.sh | bash
  USERDATA

  tags = { Name = "windy-cloud-api" }
}

resource "aws_eip" "api" {
  instance = aws_instance.api.id
  domain   = "vpc"
  tags     = { Name = "windy-cloud-api" }
}
