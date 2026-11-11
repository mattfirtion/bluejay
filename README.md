# ss-canary

AWS CloudWatch Synthetics canaries (Python/Selenium), deployed with Terraform.

## Layout
- `src/<canary>/config.yml` – canary settings (schedule, handler, alarm)
- `src/<canary>/python/<handler>.py` – canary code (same in every environment)
- `terraform/manifests` – Terraform (`alarms.tf` = CloudFront / ALB / OpenSearch alarms); Teams webhook notifier (Lambda) in `teams.tf`; discovers every `src/*/config.yml`
- `terraform/config/<env>/` – per-environment backend, variables and
  `response_plans.yml` (who is emailed through SNS when an alarm fires)

## Canaries
- `ui_journey` – browser check: host page loads, our app renders (alarm on this)
- `api_search` – plain HTTP check of the CloudFront API (tells you where a failure is)

URLs are in each `config.yml` (`environment_variables`); both are `example.com` placeholders.

## Add a canary
Copy `src/api_search`, edit `config.yml` and the handler. Handler files must use
underscores (Python import), e.g. `handler: my_check.handler`.

## Deploy
```sh
cd terraform/manifests
terraform init -backend-config=../config/dev/backend.hcl
terraform plan  -var-file=../config/dev/vars.tfvars
terraform apply -var-file=../config/dev/vars.tfvars
```
Fill in the `CHANGE-ME` values in `backend.hcl` and `vars.tfvars` first.

## Teams (optional)
1. In Teams, create a Workflow from "Post to a channel when a webhook request is received" and copy its URL.
2. Set `enable_teams = true` in `vars.tfvars` and apply.
3. Store the URL (it is never committed or put in Terraform state):
   ```sh
   aws secretsmanager put-secret-value --secret-id ss-canary-dev-teams-webhook --secret-string '<url>'
   ```
Both alarm topics are forwarded to the channel by the `teams_notifier` Lambda.
