# Shared backend settings. The bucket comes from backend-<account>.hcl (lab: dev+test, prod: staging+prod);
# the state key is set in manifests/provider.tf from var.environment.
region       = "us-east-1"
encrypt      = true
use_lockfile = true # S3-native locking, no DynamoDB
