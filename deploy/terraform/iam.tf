# --- API instance profile --------------------------------------------
# The API host only needs: read its secrets, write CloudWatch logs,
# and talk to SSM (so GitHub Actions can push deploy commands).

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "windy-cloud-api"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "api_cloudwatch" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy_attachment" "api_ssm" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "api_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:*:secret:windy-cloud/*"]
  }
}

resource "aws_iam_role_policy" "api_secrets" {
  name   = "windy-cloud-api-secrets"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_secrets.json
}

resource "aws_iam_instance_profile" "api" {
  name = "windy-cloud-api"
  role = aws_iam_role.api.name
}

# --- GitHub Actions deploy role --------------------------------------
# Assumed via OIDC from the configured repo. Lets the deploy job call
# SSM SendCommand to run the deploy script on the API host without us
# ever handing it an AWS access key.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:*"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "windy-cloud-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

data "aws_iam_policy_document" "deploy" {
  statement {
    actions = [
      "ssm:SendCommand",
      "ssm:GetCommandInvocation",
      "ssm:DescribeInstanceInformation",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = ["windy-cloud"]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "windy-cloud-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
