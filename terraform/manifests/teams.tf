# Posts alarm notifications to a Microsoft Teams channel through a Workflows webhook
# ("When a Teams webhook request is received"). Skipped unless enable_teams = true.
#
# After apply, store the webhook URL (kept out of git and Terraform state):
#   aws secretsmanager put-secret-value --secret-id ss-canary-<env>-teams-webhook \
#     --secret-string '<webhook url>'

resource "aws_secretsmanager_secret" "teams_webhook" {
  count = var.enable_teams ? 1 : 0
  name  = "ss-canary-${var.environment}-teams-webhook"
}

data "archive_file" "teams_notifier" {
  type        = "zip"
  source_file = "${path.module}/lambda/teams_notifier.py"
  output_path = "${path.module}/.build/teams_notifier.zip"
}

resource "aws_iam_role" "teams_notifier" {
  count = var.enable_teams ? 1 : 0
  name  = "ss-canary-${var.environment}-teams-notifier"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "teams_notifier" {
  count = var.enable_teams ? 1 : 0
  role  = aws_iam_role.teams_notifier[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.teams_webhook[0].arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
    ]
  })
}

resource "aws_lambda_function" "teams_notifier" {
  count = var.enable_teams ? 1 : 0

  function_name    = "ss-canary-${var.environment}-teams-notifier"
  role             = aws_iam_role.teams_notifier[0].arn
  runtime          = "python3.12"
  handler          = "teams_notifier.handler"
  filename         = data.archive_file.teams_notifier.output_path
  source_code_hash = data.archive_file.teams_notifier.output_base64sha256
  timeout          = 15

  environment {
    variables = { WEBHOOK_SECRET_ARN = aws_secretsmanager_secret.teams_webhook[0].arn }
  }
}

resource "aws_lambda_permission" "sns" {
  for_each = var.enable_teams ? {
    main       = aws_sns_topic.alerts[var.alarm_response_plan].arn
    cloudfront = aws_sns_topic.cloudfront_alerts.arn
  } : {}

  statement_id  = "AllowSNS-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.teams_notifier[0].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = each.value
}

resource "aws_sns_topic_subscription" "teams" {
  count = var.enable_teams ? 1 : 0

  topic_arn = aws_sns_topic.alerts[var.alarm_response_plan].arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.teams_notifier[0].arn
}

# Cross-region SNS -> Lambda delivery is supported; the subscription lives in the topic's region.
resource "aws_sns_topic_subscription" "teams_cloudfront" {
  count    = var.enable_teams ? 1 : 0
  provider = aws.us_east_1

  topic_arn = aws_sns_topic.cloudfront_alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.teams_notifier[0].arn
}
