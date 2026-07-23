variable "env" {
  type = string
}

variable "app_name" {
  type = string
}

variable "vpc_name" {
  type    = string
  default = "mlops_vpc"
}

variable "cidr_range" {
  type    = string
  default = "10.1.0.0/16"
}

variable "private_subnet_range" {
  type    = list(string)
  default = ["10.1.1.0/28", "10.1.2.0/28"]
}

variable "public_subnet_range" {
  type    = list(string)
  default = ["10.1.101.0/28", "10.1.102.0/28"]
}

variable "database_subnet_range" {
  type    = list(string)
  default = ["10.1.201.0/28", "10.1.202.0/28"]
}