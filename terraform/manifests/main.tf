data "aws_caller_identity" "current" {}

locals {
  src_dir        = "${path.module}/../../src"
  response_plans = yamldecode(file("${path.module}/../config/${var.environment}/response_plans.yml"))

  # One canary per src/<name>/config.yml, deployed to every environment
  canaries = {
    for f in fileset(local.src_dir, "*/config.yml") :
    dirname(f) => yamldecode(file("${local.src_dir}/${f}"))
  }
}

resource "aws_s3_bucket" "artifacts" {
  bucket        = "ss-canary-${var.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_role" "canary" {
  name = "ss-canary-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "canary" {
  role = aws_iam_role.canary.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetBucketLocation"]
        Resource = aws_s3_bucket.artifacts.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListAllMyBuckets", "xray:PutTraceSegments"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/cwsyn-*"
      },
      {
        Effect    = "Allow"
        Action    = "cloudwatch:PutMetricData"
        Resource  = "*"
        Condition = { StringEquals = { "cloudwatch:namespace" = "CloudWatchSynthetics" } }
      },
    ]
  })
}

# Synthetics requires the code under python/ inside the zip.
data "archive_file" "canary" {
  for_each    = local.canaries
  type        = "zip"
  source_dir  = "${local.src_dir}/${each.key}"
  excludes    = ["config.yml"]
  output_path = "${path.module}/.build/${each.key}.zip"
}

resource "aws_synthetics_canary" "this" {
  for_each = local.canaries

  name                 = "${var.environment}-${replace(each.value.name, "_", "-")}" # max 21 chars
  artifact_s3_location = "s3://${aws_s3_bucket.artifacts.bucket}/${each.key}/"
  execution_role_arn   = aws_iam_role.canary.arn
  handler              = each.value.handler
  runtime_version      = each.value.runtime_version
  zip_file             = data.archive_file.canary[each.key].output_path
  start_canary         = true

  success_retention_period = each.value.success_retention_days
  failure_retention_period = each.value.failure_retention_days

  schedule {
    expression = each.value.schedule
  }

  run_config {
    timeout_in_seconds = each.value.timeout_in_seconds
    memory_in_mb       = each.value.memory_in_mb
    active_tracing     = each.value.active_tracing
    environment_variables = try(each.value.environment_variables, {})
  }

  dynamic "vpc_config" {
    for_each = try(each.value.vpc, null) == null ? [] : [each.value.vpc]
    content {
      subnet_ids         = vpc_config.value.subnet_ids
      security_group_ids = vpc_config.value.security_group_ids
    }
  }
}

resource "aws_sns_topic" "alerts" {
  for_each = local.response_plans
  name     = "ss-canary-${var.environment}-${each.key}"
}

resource "aws_sns_topic_subscription" "email" {
  for_each = {
    for pair in flatten([
      for plan, v in local.response_plans : [
        for e in v.emails : { key = "${plan}/${e}", plan = plan, email = e }
      ]
    ]) : pair.key => pair
  }

  topic_arn = aws_sns_topic.alerts[each.value.plan].arn
  protocol  = "email"
  endpoint  = each.value.email
}

resource "aws_cloudwatch_metric_alarm" "failed" {
  for_each = local.canaries

  alarm_name          = "ss-canary-${var.environment}-${each.key}-failed"
  namespace           = "CloudWatchSynthetics"
  metric_name         = "SuccessPercent"
  dimensions          = { CanaryName = aws_synthetics_canary.this[each.key].name }
  statistic           = "Average"
  period              = try(each.value.alarm.period_seconds, 300)
  comparison_operator = "LessThanThreshold"
  threshold           = 100
  evaluation_periods  = each.value.alarm.evaluation_periods
  datapoints_to_alarm = each.value.alarm.datapoints_to_alarm
  treat_missing_data  = "breaching"

  alarm_actions = [aws_sns_topic.alerts[each.value.alarm.response_plan].arn]
  ok_actions    = [aws_sns_topic.alerts[each.value.alarm.response_plan].arn]
}
