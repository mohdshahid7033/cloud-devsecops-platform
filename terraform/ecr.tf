# ==============================================================================
# Amazon Elastic Container Registry (ECR) Repository
#
# Stores immutable Docker images built by GitHub Actions CI/CD.
# Configured with:
#   - Image scan on push for automated vulnerability detection
#   - Tag immutability option
#   - Lifecycle policy to clean up untagged / old images (cost optimization)
# ==============================================================================

resource "aws_ecr_repository" "devsecops_platform" {
  name                 = "devsecops-platform"
  image_tag_mutability = "MUTABLE" # Set to MUTABLE to support :latest while using commit-sha tags

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name        = "devsecops-platform"
    Project     = "devsecops-platform"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

# Lifecycle policy: retain last 30 tagged images, expire untagged after 7 days
resource "aws_ecr_lifecycle_policy" "devsecops_platform_lifecycle" {
  repository = aws_ecr_repository.devsecops_platform.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images older than 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Retain at most 30 tagged deployment images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-", "v", "build-"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
