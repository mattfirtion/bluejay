variable "environment" {
  type        = string
  description = "Environment name; selects terraform/config/<environment>/"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "alarm_response_plan" {
  type        = string
  default     = "default"
  description = "Key in config/response_plans.yml (or env overrides.yml) that receives infrastructure alarms"
}

variable "cloudfront_distribution_id" {
  type        = string
  description = "CloudFront distribution ID (alarms are created in us-east-1)"
}

variable "alb_arn_suffix" {
  type        = string
  description = "Internal ALB arn_suffix, e.g. app/my-alb/1234567890abcdef"
}

variable "target_group_arn_suffix" {
  type        = string
  description = "Target group arn_suffix, e.g. targetgroup/my-tg/1234567890abcdef"
}

variable "opensearch_domain_name" {
  type        = string
  description = "OpenSearch domain name"
}

variable "opensearch_free_storage_min_mb" {
  type        = number
  default     = 20480
  description = "Alarm when FreeStorageSpace (MB) drops below this"
}

# Microsoft Teams webhook notifications (see teams.tf). The webhook URL itself is stored
# in Secrets Manager, not here.
variable "enable_teams" {
  type    = bool
  default = false
}
