resource "aws_ecr_repository" "ecr_repo" {
  name                 = "${var.app_name}-${var.env}-repo"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "null_resource" "app_image" {
  triggers = {
    app_docker_file = ""
  }

  provisioner "local-exec" {
    # command     = <<EOT
    #   sudo aws ecr get-login-password --region ${var.region} | sudo docker login --username AWS --password-stdin ${aws_ecr_repository.ecr_repo.repository_url}
    #   sudo docker build -t ${aws_ecr_repository.ecr_repo.repository_url}:${var.ecr_image_tag} .
    #   sudo docker push ${aws_ecr_repository.ecr_repo.repository_url}:${var.ecr_image_tag}
    #   EOT

    command = <<EOT
      aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${aws_ecr_repository.ecr_repo.repository_url}
      docker build -t ${aws_ecr_repository.ecr_repo.repository_url}:${var.ecr_image_tag} .
      docker push ${aws_ecr_repository.ecr_repo.repository_url}:${var.ecr_image_tag}
      EOT

    interpreter = ["bash", "-c"]
    working_dir = "${path.root}/.."
  }

}

output "ecr_repo_url_tag" {
  value = "${aws_ecr_repository.ecr_repo.repository_url}:${var.ecr_image_tag}"
}