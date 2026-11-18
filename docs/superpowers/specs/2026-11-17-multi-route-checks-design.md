# Multi-route synthetic checks: design

Status: draft for approval. Scope: synthetic checks only. Alert email formatting is a separate follow-up.

## Intent and why

The service must hold 99.9% uptime (about 43.8 minutes of downtime per month). Today the repo has one HTTP canary hitting a single URL and one browser canary. We need to know quickly when users cannot load or use search, and which layer failed, using checks that map to the real request path.

## The system

- Users visit `www.mydomain.com/search`. That page is owned by a **separate team**. It loads `https://search.mydomain.com/index.js`, which renders our app.
- `search.mydomain.com` is ours. One CloudFront distribution fronts two origins:
  - `/index.js` is served from **S3**. It is marked no-cache and S3 is considered very reliable.
  - `/api/q` goes through a **VPC origin** to an internal ALB and the API, which queries OpenSearch. This is where crashes are expected.
- Searches are `POST /api/q` with a JSON body.
- The ALB health-checks targets every 30s. Per the team the check is intended to be a readiness check (unverified, see Assumptions).

## Goals

1. Detect an outage on `search.mydomain.com` within about 2 minutes.
2. Tell which layer failed from which checks fail.
3. Produce an uptime figure for `search.mydomain.com` that excludes problems the team does not own.

## Non-goals

- Formatted alert emails (SES or otherwise). Separate follow-up design.
- An in-VPC canary against the ALB. ALB health checks every 30s plus the `unhealthy-hosts` alarm already cover the backend directly.
- Changing the CloudFront, ALB or OpenSearch metric alarms.
- Per-route custom metrics or alarms for the HTTP checks.

## Anti-goals

- Counting a `www` (other team) outage against our 99.9%.
- Paging on one flaky run.
- Passing when `/api/q` returns 200 with empty or malformed results.

## Design

### Canaries

| Canary | Type | Cadence | Checks |
|---|---|---|---|
| `http_checks` (replaces `api_search`) | Plain Python HTTP, no browser | every 1 minute | `GET search.mydomain.com/index.js`; `POST search.mydomain.com/api/q` |
| `ui_journey` | Python/Selenium | every 30 minutes (was 15) | Load `www.mydomain.com/search`, app renders, one search returns results |

Notes:
- Synthetics bills per run, so putting both HTTP checks in one canary costs the same as one. At 1 minute that is roughly $52/month. `ui_journey` at 30 minutes is roughly $2/month plus browser overhead.
- Both HTTP checks always run, even if the first fails. The canary then fails with a message naming every failing route, so one run reports both.
- `index.js` check: status 200, JavaScript content type, non-trivial body size, latency under a threshold. No cache-buster (the object is no-cache and S3 is hit directly).
- `/api/q` check: POST a configured JSON body from `config.yml`. Assert status 200, latency under `MAX_LATENCY_MS`, valid JSON, and a result shape that proves a real search ran (not just 200). No cache-buster (CloudFront does not cache POST by default). The request body and expected shape are placeholders until the real ones are supplied.
- Send `User-Agent: ss-canary`.
- Both alarm on 2 failed datapoints out of 2, with missing data counted as breaching (so a canary that stops running alarms). The alarm period is currently hardcoded to 300s in `terraform/manifests/main.tf`, which would make 2-of-2 take about 10 minutes. Add a per-canary `alarm.period_seconds` to `config.yml`: `http_checks` uses 60 (alert in about 2 minutes), `ui_journey` uses 1800 (matches its schedule; heads-up in about an hour).
- `ui_journey` hits the other team's page. They have confirmed automated visits are fine (they run canaries too).

### Reading the signals (replaces the table in `docs/monitoring-plan.md`)

| `index.js` | `/api/q` | `ui_journey` | Likely cause |
|---|---|---|---|
| fail | pass | any | S3 origin or front-end deploy |
| pass | fail | any | VPC origin, ALB, API, or OpenSearch (check the ALB `unhealthy-hosts` alarm) |
| fail | fail | any | CloudFront or DNS |
| pass | pass | fail | `www` page or its integration (other team), or a front-end build issue |

The `http_checks` canary has a single `SuccessPercent` metric and a single alarm (decided by the owner). The failing route(s) are read from the failure message in the alarm and the canary logs, so the table above is a runbook for reading that message, not a set of separate alarms. Per-route custom metrics and alarms are out of scope and can be added later.

### Alarms and notification routing

- `http_checks` alarms use the existing `default` response plan (a real outage on our side).
- `ui_journey` alarms use a new, lower-priority response plan (for example `partner`), so a `ui_journey`-only failure is a heads-up and not an outage page. This is the designer's call (see Calls made). The `partner` plan starts with the same email recipients as `default`, sends OK notifications too, and gets its own subscription for the Teams notifier Lambda (today `teams.tf` subscribes only the default plan topic and the CloudFront topic).
- No change to existing metric alarms. A backend crash should usually raise both `unhealthy-hosts` and the `/api/q` canary alarm.

### Uptime measurement

The uptime SLI is the success rate of `http_checks` (`SuccessPercent` metric), which covers only `search.mydomain.com`. `ui_journey` is excluded from the SLI. Reporting and dashboards are out of scope here.

## Assumptions to verify

- The ALB health check path is a true readiness check that touches OpenSearch. If it only proves the process is alive, the `/api/q` canary is the only check for "up but cannot search".
- The `/api/q` real request body and a healthy response shape (not yet provided).
- The `index.js` expected content type and a minimum size.

## Constraints

- Canary code is the same in every environment. Only `terraform/config/<env>/` differs.
- Handler filenames use underscores (Python import).
- Webhook and secrets handling stays as in the existing Teams design.

## Left to the builder

- File layout of `http_checks` (one handler with two check functions is fine).
- How to extend the Terraform canary module for per-canary response plans, if it does not already allow it.
- Thresholds for `index.js` latency and minimum size.
- Updating `README.md` and `docs/monitoring-plan.md` (canary table, signal table, TODOs; mark the `/ready` and in-VPC canary TODOs as dropped, and the partner-approval TODO as done).

## Calls made by the designer (please check)

- One canary for both HTTP routes at 1 minute, not two canaries.
- `ui_journey` at 30 minutes.
- A separate lower-priority response plan for `ui_journey`.
- 2-of-2 alarming kept.
- In-VPC canary dropped.
- No cache-buster on either HTTP check.
- Per-canary alarm period in `config.yml` (60s and 1800s), missing data still counted as breaching.
- `partner` plan: same recipients as `default`, OK notifications on, Teams subscription added.
- `api_search` is replaced: its canary, alarm and artifacts are destroyed and `http_checks` starts with fresh history.
- The SLI (`http_checks` `SuccessPercent`) has no dashboard or alarm in this design. A missed run counts as a failure.
- The real search every minute is acceptable load on OpenSearch, and the request body lives in `config.yml` as an environment variable.
