# ==============================================================================
# IAM Role and Instance Profile for DevSecOps EC2
#
# The EC2 instance requires:
#   1. SSM Agent connectivity (AWS-managed SSM policy)
#   2. ECR image pull access (read-only from the devsecops-platform repository)
#   3. SSM Parameter Store read access (for DB_PASSWORD, DB_ROOT_PASSWORD, etc.)
#   4. CloudWatch Logs write access (for application and container logs)
#
# NOTE: AWS credentials for GitHub Actions are separate (IAM user with
#       ssm:SendCommand, ssm:GetCommandInvocation, ecr:GetAuthorizationToken,
#       ecr:BatchGetImage permissions) and are NOT managed here.
# ==============================================================================

# Trust policy: allow EC2 service to assume this role
data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "devsecops_ec2_role" {
  name               = "devsecops-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json

  tags = {
    Name        = "devsecops-ec2-role"
    Project     = "devsecops-platform"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

# Attach AWS-managed SSM policy (enables SSM Agent, SSM Run Command, Session Manager)
resource "aws_iam_role_policy_attachment" "ssm_managed_policy" {
  role       = aws_iam_role.devsecops_ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Attach AWS-managed CloudWatch agent policy (enables metrics/log streaming)
resource "aws_iam_role_policy_attachment" "cloudwatch_managed_policy" {
  role       = aws_iam_role.devsecops_ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# Least-privilege inline policy: ECR image pull + SSM Parameter Store read
data "aws_iam_policy_document" "devsecops_ec2_permissions" {
  # ECR: Authenticate and pull images from the devsecops-platform repository
  statement {
    sid    = "ECRAuthToken"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken"
    ]
    # GetAuthorizationToken does not support resource-level restrictions
    resources = ["*"]
  }

  statement {
    sid    = "ECRImagePull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:DescribeRepositories",
      "ecr:ListImages"
    ]
    resources = [
      "arn:aws:ecr:${var.aws_region}:*:repository/devsecops-platform"
    ]
  }

  # SSM Parameter Store: read application configuration and database credentials
  statement {
    sid    = "SSMParameterRead"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath"
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:*:parameter/devsecops/*"
    ]
  }
}

resource "aws_iam_role_policy" "devsecops_ec2_inline" {
  name   = "devsecops-ec2-inline-policy"
  role   = aws_iam_role.devsecops_ec2_role.id
  policy = data.aws_iam_policy_document.devsecops_ec2_permissions.json
}

# Instance profile - wraps the role for EC2 attachment
resource "aws_iam_instance_profile" "devsecops_ec2_profile" {
  name = "devsecops-ec2-profile"
  role = aws_iam_role.devsecops_ec2_role.name

  tags = {
    Name        = "devsecops-ec2-profile"
    Project     = "devsecops-platform"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

# ==============================================================================
# GitHub Actions OIDC Authentication & Deployer Role
#
# Allows GitHub Actions workflows to assume a role via OpenID Connect (OIDC)
# without requiring long-lived static AWS access keys.
#
# Security Hardening:
#   - Restricted to repo:mohdshahid7033/cloud-devsecops-platform
#   - Gated exclusively to pushes on the main branch (ref:refs/heads/main)
#   - PRs and feature branches cannot assume this role
#   - Scoped least-privilege permissions:
#       1. ECR image push/pull for devsecops-platform
#       2. EC2 instance & IP resolution via tags (Project=devsecops-platform)
#       3. SSM command execution on tagged instances
#       4. SSM Parameter Store access for /devsecops/* parameters
# ==============================================================================

# Create OIDC Provider only if not already present in the AWS account
resource "aws_iam_openid_connect_provider" "github_actions" {
  count = var.create_github_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1c58a3a8518e8759bf075b76b750d4f8d7040716"]

  tags = {
    Name        = "github-actions-oidc"
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Account ID discovery for OIDC provider ARN
data "aws_caller_identity" "current" {}

locals {
  github_oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github_actions[0].arn : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

# Trust policy for GitHub Actions deployer role
data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    sid     = "GitHubActionsOIDC"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/${var.github_branch}"]
    }
  }
}

resource "aws_iam_role" "github_actions_deployer" {
  name               = "devsecops-github-deployer-role"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json

  tags = {
    Name        = "devsecops-github-deployer-role"
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Least-privilege deployer policy
data "aws_iam_policy_document" "github_actions_deployer_permissions" {
  # 1. ECR image publish permissions
  statement {
    sid    = "ECRAuthToken"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ECRImagePushPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeRepositories",
      "ecr:ListImages"
    ]
    resources = [
      "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/devsecops-platform"
    ]
  }

  # 2. Dynamic EC2 target discovery by tags
  statement {
    sid    = "EC2DiscoveryByTags"
    effect = "Allow"
    actions = [
      "ec2:DescribeInstances"
    ]
    resources = ["*"]
  }

  # 3. SSM Run Command dispatch and polling
  statement {
    sid    = "SSMRunCommand"
    effect = "Allow"
    actions = [
      "ssm:SendCommand"
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript",
      "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/*"
    ]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }
  }

  statement {
    sid    = "SSMCommandStatus"
    effect = "Allow"
    actions = [
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "ssm:ListCommands"
    ]
    resources = ["*"]
  }

  # 4. SSM Parameter Store configuration access
  statement {
    sid    = "SSMParameterRead"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters"
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/devsecops/*"
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_deployer_inline" {
  name   = "devsecops-github-deployer-policy"
  role   = aws_iam_role.github_actions_deployer.id
  policy = data.aws_iam_policy_document.github_actions_deployer_permissions.json
}
