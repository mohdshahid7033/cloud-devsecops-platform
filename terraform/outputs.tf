output "vpc_id" {
  description = "ID of the DevSecOps VPC"
  value       = aws_vpc.devsecops_vpc.id
}

output "subnet_id" {
  description = "ID of the DevSecOps subnet"
  value       = aws_subnet.devsecops_subnet.id
}

output "security_group_id" {
  description = "ID of the DevSecOps security group"
  value       = aws_security_group.devsecops_sg.id
}

output "ec2_instance_id" {
  description = "ID of the DevSecOps EC2 instance"
  value       = aws_instance.devsecops_ec2.id
}

output "ec2_public_ip" {
  description = "Public IP address of the DevSecOps EC2 instance"
  value       = aws_instance.devsecops_ec2.public_ip
}

output "ecr_repository_url" {
  description = "URL of the Amazon ECR repository"
  value       = aws_ecr_repository.devsecops_platform.repository_url
}

output "iam_instance_profile_name" {
  description = "Name of the EC2 IAM instance profile"
  value       = aws_iam_instance_profile.devsecops_ec2_profile.name
}

output "iam_role_arn" {
  description = "ARN of the EC2 IAM role"
  value       = aws_iam_role.devsecops_ec2_role.arn
}

output "github_actions_deployer_role_arn" {
  description = "ARN of the IAM role assumed by GitHub Actions for blue/green deployment"
  value       = aws_iam_role.github_actions_deployer.arn
}
