# Monitoring plan

## Architecture being monitored

```
User ─► Partner site (hosts our UI) ─► CloudFront ─► VPC origin ─► Internal ALB ─► API (private subnet) ─► OpenSearch
```

- The UI is served from another website that embeds our app.
- The API is reached through CloudFront, which connects to the private subnet over a VPC origin.
- The API queries OpenSearch.

## Goals
1. Know when users can't load the app or run a search, before they tell us.
2. When something breaks, know which layer: partner page/UI, CloudFront/edge, backend, or OpenSearch.
3. Notify by email (SNS) and a Teams channel, with no dependency on a product that is being retired.

## Layers

| Layer | What | Where it's defined |
|---|---|---|
| Synthetic: user journey | Browser loads the partner page, our app renders, search returns results | `src/ui_journey` |
| Synthetic: API | Plain HTTP search call through CloudFront (cache-busted), asserts status, latency, JSON shape | `src/api_search` |
| Synthetic: origin (optional) | Same HTTP check run inside the VPC against the internal ALB/health endpoint | add a canary with `vpc:` in `config.yml` |
| Metric alarms | CloudFront, ALB/target group, OpenSearch | `terraform/manifests/alarms.tf` |
| Notification | SNS email, optional Teams webhook | `main.tf`, `teams.tf`, `config/<env>/response_plans.yml` |

### Reading the signals

| `ui_journey` | `api_search` | Likely cause |
|---|---|---|
| fail | pass | Partner page, front-end build, CORS/CSP, or partner-site outage |
| fail | fail | CloudFront, VPC origin, backend, or OpenSearch |
| pass | fail | API-only problem (e.g. an endpoint the UI doesn't hit) |

Alarm on the user journey (what users see); use the API canary to localize.

## Canaries

| Canary | Runtime | Schedule | Memory | Notes |
|---|---|---|---|---|
| `ui_journey` | Python/Selenium (`syn-python-selenium-5.1`) | every 15 min | 960 MB | Waits for the app root element, fails on severe browser console errors |
| `api_search` | Python, plain `urllib` (no browser) | every 5 min | 512 MB | Unique `cb` query param defeats the CDN cache; `User-Agent: ss-canary` |

Both alarm on 2 failed datapoints out of 2 to avoid paging on a single flaky run
(`alarm.datapoints_to_alarm` / `evaluation_periods`). Missing data counts as breaching,
so a canary that stops running alarms too.

Considerations for the partner-page canary:
- Confirm the partner is fine with automated traffic; allow-list the `ss-canary` User-Agent.
- Failures can originate on their side; the API canary is how we tell the difference.
- Filter synthetic traffic out of analytics by User-Agent.
- Cost scales with frequency (roughly $10-15/month at 5-minute intervals for a browser canary).

## Metric alarms (boilerplate thresholds)

Thresholds are defaults and should be tuned once there is real traffic.

**CloudFront** (alarms live in `us-east-1`, the only region CloudFront publishes to)
| Alarm | Metric | Threshold |
|---|---|---|
| 5xx-error-rate | `5xxErrorRate` | > 5% for 3 min |
| 4xx-error-rate | `4xxErrorRate` | > 20% for 3 min |
| origin-latency | `OriginLatency` p95 | > 3000 ms for 3 min |

**ALB / backend**
| Alarm | Metric | Threshold |
|---|---|---|
| unhealthy-hosts | `UnHealthyHostCount` | > 0 for 2 min |
| target-5xx | `HTTPCode_Target_5XX_Count` | > 10 for 3 min |
| response-time | `TargetResponseTime` p95 | > 2 s for 3 min |

**OpenSearch**
| Alarm | Metric | Threshold |
|---|---|---|
| cluster-red | `ClusterStatus.red` | >= 1 |
| cluster-yellow | `ClusterStatus.yellow` | >= 1 for 25 min |
| writes-blocked | `ClusterIndexWritesBlocked` | >= 1 |
| free-storage | `FreeStorageSpace` | < 20 GB (variable) |
| cpu | `CPUUtilization` | > 80% for 15 min |
| jvm-pressure | `JVMMemoryPressure` | > 80% for 15 min |
| search-rejected | `ThreadpoolSearchRejected` | > 0 for 15 min |
| 5xx | `5xx` | > 5 for 15 min |

Missing data is treated as not breaching for these (the canaries cover "everything is down").

## Notifications

- Every alarm publishes to an SNS topic on ALARM and OK.
- Recipients are defined per environment in `terraform/config/<env>/response_plans.yml`;
  each plan key becomes one topic with the listed email subscribers.
- Optional Teams channel: a small Lambda (`terraform/manifests/lambda/teams_notifier.py`)
  is subscribed to the topics and posts an Adaptive Card to a Teams Workflows webhook.
  The webhook URL lives in Secrets Manager (`ss-canary-<env>-teams-webhook`), never in git
  or Terraform state. Enable with `enable_teams = true`.
- CloudFront alarms use a separate `us-east-1` topic (alarm actions must be in the alarm's
  own region); it has the same email subscribers and feeds the same Teams Lambda.

### Decision record: why not Incident Manager / OpsCenter
- **SSM Incident Manager** is closed to new customers; we don't want to build on it even
  though it exists in the account.
- **SSM OpsCenter** is AWS's suggested replacement, but it only tracks work items: no
  paging, on-call, or escalation. It adds little over email/Teams for this use.
- SNS is the stable notification layer. If paging is needed later (PagerDuty, Opsgenie),
  subscribe it to the same topics; no alarm changes are required.

## Environments
Canary code is the same in every environment (`src/<canary>/`). Only
`terraform/config/<env>/` differs: backend, variables (CloudFront/ALB/OpenSearch
identifiers, `enable_teams`) and `response_plans.yml`. Add an environment by copying
`config/dev` and passing it to `terraform init -backend-config` / `-var-file`.

## Open items / TODO
- [ ] Replace `example.com` URLs in `src/*/config.yml` (`PAGE_URL`, `API_URL`).
- [ ] Set real selectors for the app root, search box and results in `ui_journey.py`, and finish the search-and-assert step.
- [ ] Assert the real JSON shape in `api_search.py`.
- [ ] Add a `/ready` endpoint on the API that checks OpenSearch, and decide on an in-VPC origin canary.
- [ ] Fill `CHANGE-ME` values in `backend.hcl` and `vars.tfvars` (state bucket/lock table, CloudFront ID, ALB and target group suffixes, OpenSearch domain).
- [ ] Confirm with the partner that automated visits to their page are OK.
- [ ] Run `terraform fmt` / `validate` / `plan` (not yet run; Terraform wasn't available when this was written).
- [ ] Create the Teams Workflows webhook, enable `enable_teams`, store the URL in Secrets Manager, and test with a manual alarm state change.
- [ ] Tune alarm thresholds after a couple of weeks of real data.
