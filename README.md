# ss-canary

AWS CloudWatch Synthetics canaries (Python/Selenium), deployed with Terraform.

See [docs/monitoring-plan.md](docs/monitoring-plan.md) for the monitoring plan, alarm thresholds,
notification design and open TODOs.

## Layout
- `src/<canary>/config.yml` – canary settings (schedule, handler, alarm)
- `src/<canary>/python/<handler>.py` – canary code (same in every environment)
- `terraform/manifests` – Terraform (`alarms.tf` = CloudFront / ALB / OpenSearch alarms); Teams webhook notifier (Lambda) in `teams.tf`; discovers every `src/*/config.yml`
- `terraform/config/<env>/` – per-environment backend, variables and
  `response_plans.yml` (who is emailed through SNS when an alarm fires)

## Canaries
- `http_checks` – every minute: `GET search.mydomain.com/index.js` (S3) and `POST search.mydomain.com/api/q` (VPC origin). Both run every time; a failure names the failing route. The 99.9% uptime figure comes from this canary only.
- `ui_journey` – every 30 minutes: browser check that the partner page loads and our app renders. Alerts go to the lower-priority `partner` response plan.

URLs, the `/api/q` request body and the response key are in each `config.yml` (`environment_variables`); all are placeholders.

## Test
```sh
pip install -r tests/requirements.txt
pytest tests
```

## Add a canary
Copy `src/http_checks`, edit `config.yml` and the handler. Handler files must use
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
