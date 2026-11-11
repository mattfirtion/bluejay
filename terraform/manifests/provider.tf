terraform {
  required_version = ">= 1.5"

  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }

  backend "s3" {}
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
