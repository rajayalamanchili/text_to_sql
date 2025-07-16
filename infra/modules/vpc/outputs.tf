output "vpc_id" {
  value = aws_vpc.vpc.id
}

output "cidr_block" {
  value = aws_vpc.vpc.cidr_block
}

output "vpc_public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "vpc_private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "vpc_db_subnet_ids" {
  value = aws_subnet.db[*].id
}

output "vpc_db_subnet_group_name" {
  value = aws_db_subnet_group.db_subnet_group.name
}