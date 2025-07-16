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