# Default VPC + subnets — sufficient for a single-region launch. A
# dedicated VPC with private subnets is a Wave 10 follow-up.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# --- API security group -----------------------------------------------
# Public 80 / 443 because the ALB + Caddy terminate TLS on this host
# during Wave 9. When we put a proper ALB in front (Wave 10) we'll
# narrow this to the ALB's SG instead of the open internet.

resource "aws_security_group" "api" {
  name        = "windy-cloud-api"
  description = "Windy Cloud API host"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP (Caddy autocert challenge + redirect)"
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
    description = "SSH — restrict to bastion CIDR"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.bastion_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "windy-cloud-api" }
}

# --- RDS security group -----------------------------------------------
# Only the API SG can reach Postgres. This is the single tightest
# control on the path — never widen it.

resource "aws_security_group" "db" {
  name        = "windy-cloud-db"
  description = "Windy Cloud Postgres — reachable only from the API SG"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Postgres from API host"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "windy-cloud-db" }
}
