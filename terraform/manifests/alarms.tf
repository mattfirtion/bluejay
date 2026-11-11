# Infrastructure alarms: CloudFront, ALB / backend, OpenSearch.
# Thresholds are boilerplate defaults; tune them once there is real traffic.

locals {
  alarm_topic_arn = aws_sns_topic.alerts[var.alarm_response_plan].arn

  alb_dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }
  os_dimensions = {
    DomainName = var.opensearch_domain_name
    ClientId   = data.aws_caller_identity.current.account_id
  }

  # CloudFront (us-east-1 only)
  cloudfront_alarms = {
    "5xx-error-rate" = { metric = "5xxErrorRate", stat = "Average", op = "GreaterThanThreshold", threshold = 5, periods = 3 }
    "origin-latency" = { metric = "OriginLatency", stat = "p95", op = "GreaterThanThreshold", threshold = 3000, periods = 3 }
    "4xx-error-rate" = { metric = "4xxErrorRate", stat = "Average", op = "GreaterThanThreshold", threshold = 20, periods = 3 }
  }

  # ALB target group
  alb_alarms = {
    "unhealthy-hosts" = { namespace = "AWS/ApplicationELB", metric = "UnHealthyHostCount", stat = "Maximum", op = "GreaterThanThreshold", threshold = 0, periods = 2 }
    "target-5xx"      = { namespace = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", stat = "Sum", op = "GreaterThanThreshold", threshold = 10, periods = 3 }
    "response-time"   = { namespace = "AWS/ApplicationELB", metric = "TargetResponseTime", stat = "p95", op = "GreaterThanThreshold", threshold = 2, periods = 3 }
  }

  # OpenSearch
  opensearch_alarms = {
    "cluster-red"     = { metric = "ClusterStatus.red", stat = "Maximum", op = "GreaterThanOrEqualToThreshold", threshold = 1, periods = 1 }
    "cluster-yellow"  = { metric = "ClusterStatus.yellow", stat = "Maximum", op = "GreaterThanOrEqualToThreshold", threshold = 1, periods = 5 }
    "writes-blocked"  = { metric = "ClusterIndexWritesBlocked", stat = "Maximum", op = "GreaterThanOrEqualToThreshold", threshold = 1, periods = 1 }
    "free-storage"    = { metric = "FreeStorageSpace", stat = "Minimum", op = "LessThanThreshold", threshold = var.opensearch_free_storage_min_mb, periods = 1 }
    "cpu"             = { metric = "CPUUtilization", stat = "Average", op = "GreaterThanThreshold", threshold = 80, periods = 3 }
    "jvm-pressure"    = { metric = "JVMMemoryPressure", stat = "Maximum", op = "GreaterThanThreshold", threshold = 80, periods = 3 }
    "search-rejected" = { metric = "ThreadpoolSearchRejected", stat = "Sum", op = "GreaterThanThreshold", threshold = 0, periods = 3 }
    "5xx"             = { metric = "5xx", stat = "Sum", op = "GreaterThanThreshold", threshold = 5, periods = 3 }
  }
}

# CloudWatch alarm actions must be in the alarm's region, so CloudFront alarms
# get their own us-east-1 topic with the same subscribers.
resource "aws_sns_topic" "cloudfront_alerts" {
  provider = aws.us_east_1
  name     = "ss-canary-${var.environment}-cloudfront"
}

resource "aws_sns_topic_subscription" "cloudfront_email" {
  for_each = toset(local.response_plans[var.alarm_response_plan].emails)

  provider  = aws.us_east_1
  topic_arn = aws_sns_topic.cloudfront_alerts.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_cloudwatch_metric_alarm" "cloudfront" {
  for_each = local.cloudfront_alarms
  provider = aws.us_east_1

  alarm_name          = "ss-canary-${var.environment}-cloudfront-${each.key}"
  namespace           = "AWS/CloudFront"
  metric_name         = each.value.metric
  dimensions          = { DistributionId = var.cloudfront_distribution_id, Region = "Global" }
  statistic           = contains(["p95"], each.value.stat) ? null : each.value.stat
  extended_statistic  = contains(["p95"], each.value.stat) ? each.value.stat : null
  period              = 60
  comparison_operator = each.value.op
  threshold           = each.value.threshold
  evaluation_periods  = each.value.periods
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.cloudfront_alerts.arn]
  ok_actions    = [aws_sns_topic.cloudfront_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "alb" {
  for_each = local.alb_alarms

  alarm_name          = "ss-canary-${var.environment}-alb-${each.key}"
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = local.alb_dimensions
  statistic           = contains(["p95"], each.value.stat) ? null : each.value.stat
  extended_statistic  = contains(["p95"], each.value.stat) ? each.value.stat : null
  period              = 60
  comparison_operator = each.value.op
  threshold           = each.value.threshold
  evaluation_periods  = each.value.periods
  treat_missing_data  = "notBreaching"

  alarm_actions = [local.alarm_topic_arn]
  ok_actions    = [local.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "opensearch" {
  for_each = local.opensearch_alarms

  alarm_name          = "ss-canary-${var.environment}-opensearch-${each.key}"
  namespace           = "AWS/ES"
  metric_name         = each.value.metric
  dimensions          = local.os_dimensions
  statistic           = each.value.stat
  period              = 300
  comparison_operator = each.value.op
  threshold           = each.value.threshold
  evaluation_periods  = each.value.periods
  treat_missing_data  = "notBreaching"

  alarm_actions = [local.alarm_topic_arn]
  ok_actions    = [local.alarm_topic_arn]
}
