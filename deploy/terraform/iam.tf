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

# --- User-VPS provisioning (Wave 13 Phase 3 IAM stanza) --------------
# Windy Cloud's white-label VPS feature lets end-users spin up their
# own EC2 instances *through the Cloud API* without ever seeing AWS
# credentials of their own. The Cloud API host therefore needs
# permission to call EC2 itself — but only on instances it tagged as
# `Product=user-vps` at create time, never on the Cloud's own infra.
#
# We split "Describe" (can't scope by tag per AWS policy grammar) from
# the mutating actions, which ARE tag-scoped via a Condition.

data "aws_iam_policy_document" "user_vps" {
  # Describe is read-only and can't be restricted by resource tag in
  # IAM, so we leave it on Resource="*". That's the AWS-documented
  # pattern and matches how every EC2 console user already works.
  statement {
    sid       = "DescribeEc2"
    actions   = ["ec2:DescribeInstances", "ec2:DescribeAddresses"]
    resources = ["*"]
  }

  # RunInstances is the creation path. `ec2:ResourceTag/Product` only
  # evaluates to truthy if the caller adds the Product=user-vps tag in
  # the same request (via `TagSpecifications`). The API code already
  # does this; this condition belt-and-braces enforces it so a bug in
  # application code can't silently spin up untagged instances.
  statement {
    sid     = "RunTaggedInstance"
    actions = ["ec2:RunInstances", "ec2:CreateTags"]
    resources = [
      "arn:aws:ec2:${var.aws_region}:*:instance/*",
      "arn:aws:ec2:${var.aws_region}:*:volume/*",
      "arn:aws:ec2:${var.aws_region}:*:network-interface/*",
      "arn:aws:ec2:${var.aws_region}:*:image/*",
      "arn:aws:ec2:${var.aws_region}:*:key-pair/*",
      "arn:aws:ec2:${var.aws_region}:*:security-group/*",
      "arn:aws:ec2:${var.aws_region}:*:subnet/*",
    ]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/Product"
      values   = ["user-vps"]
    }
  }

  # Lifecycle actions on already-existing instances. `ResourceTag`
  # checks the tag on the target instance itself, so these actions
  # can only ever touch instances we (or an earlier allowed Run) have
  # tagged Product=user-vps. This is the safety net against the Cloud
  # API accidentally stopping its own host.
  statement {
    sid = "LifecycleOnUserVpsOnly"
    actions = [
      "ec2:StartInstances",
      "ec2:StopInstances",
      "ec2:RebootInstances",
      "ec2:TerminateInstances",
    ]
    resources = ["arn:aws:ec2:${var.aws_region}:*:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/Product"
      values   = ["user-vps"]
    }
  }

  # Address association (the user-facing "give me a public IP for my
  # VPS" flow). Allocation is unconditional because the EIP itself has
  # no tag until it's associated; Associate is tag-scoped on the
  # target instance.
  statement {
    sid       = "AllocateEip"
    actions   = ["ec2:AllocateAddress", "ec2:ReleaseAddress"]
    resources = ["*"]
  }

  statement {
    sid       = "AssociateOnUserVpsOnly"
    actions   = ["ec2:AssociateAddress", "ec2:DisassociateAddress"]
    resources = ["arn:aws:ec2:${var.aws_region}:*:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/Product"
      values   = ["user-vps"]
    }
  }
}

resource "aws_iam_role_policy" "api_user_vps" {
  name   = "windy-cloud-api-user-vps"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.user_vps.json
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
