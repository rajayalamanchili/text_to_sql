data "aws_iam_policy" "cloud_watch" {
  name = "AWSOpsWorksCloudWatchLogs"
}

data "aws_iam_policy" "ecs_task_execution" {
  name = "AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_policy" "ecs_ssm" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "ssm:GetParameter*"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:*:*:*"
      },
    ]
  })
}

resource "aws_iam_policy" "s3_rds" {

  name = "${var.app_name}-${var.env}-s3-rds"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        "Effect" : "Allow",
        "Action" : [
          "s3:GetObject",
          "s3:List*"
        ],
        "Resource" : [
          "arn:aws:s3:::*"
        ]
      },
      {
        "Effect" : "Allow",
        "Action" : [
          "rds-db:connect"
        ],
        "Resource" : [
          "arn:aws:rds:*"
        ]
      }
    ]
  })
}

resource "aws_iam_role" "ecs_task" {
  name = "${var.app_name}-${var.env}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Effect = "Allow"
      },
    ]
  })

}

resource "aws_iam_role_policy_attachment" "ecs_task_ecs_ssm" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.ecs_ssm.arn
}

resource "aws_iam_role_policy_attachment" "ecs_task_s3_rds" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.s3_rds.arn
}

resource "aws_iam_role" "ecs_execution" {
  name = "${var.app_name}-${var.env}-ecs-execution"


  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Effect = "Allow"
      },
    ]
  })

}

resource "aws_iam_role_policy_attachment" "ecs_execution_cloud_watch" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = data.aws_iam_policy.cloud_watch.arn
}

resource "aws_iam_role_policy_attachment" "ecs_execution_ecs_task_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = data.aws_iam_policy.ecs_task_execution.arn
}

resource "aws_iam_role_policy_attachment" "ecs_execution_ecs_ssm" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_ssm.arn
}

resource "aws_iam_role_policy_attachment" "ecs_execution_s3_rds" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.s3_rds.arn
}