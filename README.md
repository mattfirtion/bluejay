# ss-canary

AWS CloudWatch Synthetics canaries (Python/Selenium), deployed with Terraform.

See [docs/monitoring-plan.md](docs/monitoring-plan.md) for the monitoring plan, alarm thresholds,
notification design and open TODOs.

## Layout
- `src/<canary>/config.yml` – canary settings (schedule, handler, alarm)
- `src/<canary>/python/<handler>.py` – canary code (same in every environment)
- `terraform/manifests` – OpenTofu/Terraform (`alarms.tf` = CloudFront / ALB / OpenSearch alarms); Teams webhook notifier (Lambda) in `teams.tf`; discovers every `src/*/config.yml`
- `terraform/manifests/common.auto.tfvars` – defaults for every env (loads automatically)
- `terraform/config/` – shared `backend.hcl`, one state bucket per account (`backend-lab.hcl` for dev/test, `backend-prod.hcl` for staging/prod), `response_plans.yml` (who is emailed through SNS when an alarm fires)
- `terraform/config/<env>/` (`dev`, `test`, `staging`, `prod`) – only the differences: `vars.tfvars` (resource IDs) and `overrides.yml` (per-env canary settings such as URLs and schedule, response plan recipients)
- `scripts/run_canary.py` – runs a canary locally in the Synthetics runtime (see below)
- `stubs/` – IDE-only type stubs for the `aws_synthetics` runtime module; `pyproject.toml` – dev dependencies (managed with `uv`)

## Canaries
- `http_checks` – every minute: `GET search.mydomain.com/index.js` (S3) and `POST search.mydomain.com/api/q` (VPC origin). Both run every time; a failure names the failing route. The 99.9% uptime figure comes from this canary only.
- `ui_journey` – every 30 minutes: browser check that the partner page loads and our app renders. Alerts go to the lower-priority `partner` response plan.

URLs, the `/api/q` request body and the response key are in each `config.yml` (`environment_variables`); all are placeholders. Per-env values go in `terraform/config/<env>/overrides.yml`, merged over `config.yml`: `environment_variables` and `alarm` merge key by key, every other key (e.g. `schedule`) is replaced. Response plans in `overrides.yml` are merged over `response_plans.yml` by plan name.

## Test
```sh
uv run pytest   # creates .venv and installs the dev group on first run
```
Requires [uv](https://docs.astral.sh/uv/).

## Add a canary
Copy `src/http_checks`, edit `config.yml` and the handler. Handler files must use
underscores (Python import), e.g. `handler: my_check.handler`. Add the new name to the canary
choices in `.vscode/tasks.json` and `.vscode/launch.json`, and to the `smoke` matrix in `.gitlab-ci.yml`.

## Deploy
Requires OpenTofu >= 1.10 (variables in the backend block, `use_lockfile`) and AWS credentials for the target account.
```sh
export TF_VAR_environment=dev   # dev | test | staging | prod
ACCOUNT=lab                     # lab for dev/test, prod for staging/prod
cd terraform/manifests          # common.auto.tfvars loads automatically
tofu init -reconfigure -backend-config=../config/backend.hcl -backend-config=../config/backend-$ACCOUNT.hcl
tofu plan  -var-file=../config/$TF_VAR_environment/vars.tfvars
tofu apply -var-file=../config/$TF_VAR_environment/vars.tfvars
```
Fill in the `CHANGE-ME` values in `backend-lab.hcl`, `backend-prod.hcl` and each env's `vars.tfvars` first. CI does this for you (see below); run it by hand only for local plans.

## Teams (optional)
1. In Teams, create a Workflow from "Post to a channel when a webhook request is received" and copy its URL.
2. Set `enable_teams = true` in `vars.tfvars` and apply.
3. Store the URL (it is never committed or put in Terraform state):
   ```sh
   aws secretsmanager put-secret-value --secret-id ss-canary-<env>-teams-webhook --secret-string '<url>'
   ```
Both alarm topics are forwarded to the channel by the `teams_notifier` Lambda.

## CI (`.gitlab-ci.yml`)
- Merge requests and the default branch: `fmt` (tofu fmt), `tflint`, `prek` (everything in `prek.toml`, incl. ruff), `kics` (non-blocking for now), `pytest`, `validate`, then `plan` for all four envs. Merge requests also run `smoke`: the real canaries in the Synthetics runtime (SAM + Docker, `scripts/run_canary.py`) against live prod URLs, no deploy (needs CI/CD vars `SYNTHETICS_LAYER_ARN`, `SYNTHETICS_LAMBDA_RUNTIME`, `SMOKE_ARTIFACT_BUCKET`).
- Deploy to any environment: Build, Run pipeline, pick the `environment` input (`dev`, `test`, `staging`, `prod`), on any branch. That plans and deploys only that env (staging and prod still need the manual click).
- Default branch only: `deploy-dev` and `deploy-test` run automatically in order; `deploy-staging` and `deploy-prod` are manual and each needs the previous env. Apply uses the saved plan from the same pipeline, and only one deploy per env runs at a time.
- Runners: one per account, tagged `account-lab` and `account-prod`; jobs that touch AWS pick theirs from the `ACCOUNT` variable.
- AWS auth: the runner is an EC2 instance; its instance role assumes the role in the CI/CD variable `AWS_ROLE_ARN`, scoped per environment (`dev`, `test`, `staging`, `prod`; mark prod protected). `dev`/`test` use account-lab, `staging`/`prod` account-prod, each with its own state bucket. Each target role must trust the instance role. Docker executor needs IMDSv2 hop limit >= 2.
- Commit `terraform/manifests/.terraform.lock.hcl` and `uv.lock`; the CI caches are keyed on them. Regenerate with `tofu init` and `uv lock`.

## Run a canary from VS Code
No deploy; runs the real canary in the Synthetics runtime (SAM + Docker) against the URLs of the env you pick.
1. Install Docker, `uv`, the AWS SAM CLI (`uv tool install aws-sam-cli`) and (for debugging) the AWS Toolkit extension. Log in to AWS (the layer is pulled with your credentials). Copy `.env.local.example` to `.env.local` and fill it in.
2. Run: Terminal, Run Task, "Run canary (SAM, no deploy)", pick canary and env.
3. Debug: Run and Debug, "Debug http_checks (SAM)" or "Debug ui_journey (SAM)", pick env; breakpoints in `src/<canary>/python/` work.
Same thing from a shell: `uv run scripts/run_canary.py <canary> <env>`.

## Pre-commit hooks (prek)
`prek.toml` runs file hygiene checks, yaml/json checks, ruff, `tofu fmt` and `tflint` on commit, and pytest on push. CI runs the same hooks (`tofu fmt` and `tflint` in their own jobs). Run `tflint --init` once per clone to fetch the AWS ruleset (`terraform/manifests/.tflint.hcl`).
```sh
prek install            # once per clone
prek run --all-files    # run everything now
```
