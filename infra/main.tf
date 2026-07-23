terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

module "vpc" {
  source = "./modules/vpc"

  app_name = var.app_name
  env      = var.env
}

module "ecr_repo" {
  source = "./modules/ecr"

}

resource "aws_security_group" "lb_sg" {
  name   = "${var.app_name}-${var.env}-ecs-lb"
  vpc_id = module.vpc.vpc_id

}

resource "aws_security_group_rule" "lb_sg_ingress" {
  type              = "ingress"
  from_port         = var.ecs_lb_listener_port
  to_port           = var.ecs_lb_listener_port
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.lb_sg.id
}

resource "aws_security_group_rule" "lb_sg_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.lb_sg.id
}

resource "aws_security_group" "ecs_service_sg" {
  name   = "${var.app_name}-${var.env}-ecs-service-sg"
  vpc_id = module.vpc.vpc_id

  ingress {
    from_port   = var.app_port
    to_port     = var.app_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

module "ecs" {
  source = "./modules/ecs"

  vpc_id                = module.vpc.vpc_id
  vpc_public_subnet_ids = module.vpc.vpc_public_subnet_ids

  ecs_lb_listener_port = var.ecs_lb_listener_port
  app_port             = var.app_port

  lb_security_group_id          = aws_security_group.lb_sg.id
  ecs_service_security_group_id = aws_security_group.ecs_service_sg.id

  ecr_repo_url = module.ecr_repo.ecr_repo_url_tag

  depends_on = [module.ecr_repo.ecr_repo_url_tag]

}

output "lb_public_dns" {
  value = module.ecs.ecs_lb_dns
}