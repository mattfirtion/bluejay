# Auto-loaded defaults for every environment. config/<env>/vars.tfvars is passed with -var-file and wins.
# `environment` is not set here: export TF_VAR_environment=<env>.
region                         = "us-east-1"
alarm_response_plan            = "default"
opensearch_free_storage_min_mb = 20480
