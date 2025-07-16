data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_subnet" "private" {
  vpc_id = aws_vpc.vpc.id

  count             = length(var.private_subnet_range)
  cidr_block        = element(var.private_subnet_range, count.index)
  availability_zone = element(data.aws_availability_zones.available.names, count.index)

  tags = {
    Name        = "${var.app_name}-vpc"
    Environment = var.env
  }

}

resource "aws_subnet" "public" {
  vpc_id = aws_vpc.vpc.id

  count             = length(var.public_subnet_range)
  cidr_block        = element(var.public_subnet_range, count.index)
  availability_zone = element(data.aws_availability_zones.available.names, count.index)

  map_public_ip_on_launch = true

  tags = {
    Name        = "${var.app_name}-vpc"
    Environment = var.env
  }

}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.vpc.id

  tags = {
    Name        = "${var.app_name}-vpc"
    Environment = var.env
  }

}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.vpc.id

  tags = {
    Name        = "${var.app_name}-vpc"
    Environment = var.env
  }

}

resource "aws_route" "public" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.igw.id


}

resource "aws_route_table_association" "public" {
  route_table_id = aws_route_table.public.id

  count     = length(var.public_subnet_range)
  subnet_id = element(aws_subnet.public.*.id, count.index)

}

resource "aws_subnet" "db" {
  vpc_id = aws_vpc.vpc.id

  count             = length(var.database_subnet_range)
  cidr_block        = element(var.database_subnet_range, count.index)
  availability_zone = element(data.aws_availability_zones.available.names, count.index)

  tags = {
    Name        = "${var.app_name}-vpc"
    Environment = var.env
  }

}

resource "aws_db_subnet_group" "db_subnet_group" {
  name       = "${var.app_name}-db-subnet-group"
  subnet_ids = aws_subnet.db.*.id

  tags = {
    Name        = "${var.app_name}-vpc"
    Environment = var.env
  }

}