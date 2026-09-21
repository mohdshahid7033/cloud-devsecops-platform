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
