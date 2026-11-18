terraform {
  required_version = ">= 1.5"

  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }

  # OpenTofu 1.8+: variables allowed here. Key is per-env; the bucket comes from -backend-config.
  backend "s3" {
    key = "ss-canary/${var.environment}/terraform.tfstate"
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "ss-canary", Environment = var.environment }
  }
}

# CloudFront publishes its metrics only in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = { Project = "ss-canary", Environment = var.environment }
  }
}
