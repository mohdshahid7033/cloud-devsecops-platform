variable "aws_region" {
  description = "AWS region where infrastructure will be deployed"
  type        = string
  default     = "ap-south-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "ami_id" {
  description = "AMI ID for the EC2 instance"
  type        = string
  default     = "ami-0ee11497c4eac651d"
}

variable "availability_zone" {
  description = "Availability zone for the subnet"
  type        = string
  default     = "ap-south-1a"
}

variable "key_name" {
  description = "EC2 Key Pair name for SSH emergency access (optional, SSM preferred)"
  type        = string
  default     = "devsecops-key"
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "production"
}

variable "project_name" {
  description = "Project name tag"
  type        = string
  default     = "devsecops-platform"
}

variable "github_repository" {
  description = "GitHub repository path for OIDC authentication (owner/repo)"
  type        = string
  default     = "mohdshahid7033/cloud-devsecops-platform"
}

variable "github_branch" {
  description = "Target branch for GitHub Actions OIDC deployments"
  type        = string
  default     = "main"
}

variable "create_github_oidc_provider" {
  description = "Whether to create the AWS IAM OIDC provider for GitHub (set false if provider already exists in the AWS account)"
  type        = bool
  default     = false
}
