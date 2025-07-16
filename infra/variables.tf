variable "env" {
  default = "dev"
}

variable "app_name" {
  default = "mlops"
}

variable "region" {
  default = "us-east-2"
}

variable "ecs_lb_listener_port" {
  type    = number
  default = 80
}

variable "app_port" {
  type    = number
  default = 8501
}