# Multi-route Synthetic Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-URL `api_search` canary with a 1-minute `http_checks` canary covering `index.js` (S3) and `POST /api/q` (VPC origin), slow `ui_journey` to 30 minutes, and route its alerts to a lower-priority `partner` plan.

**Architecture:** One new plain-HTTP canary runs both checks every run, collects all failures, and raises one exception naming each failing route. Terraform gains a per-canary alarm period and a second response plan wired to the Teams notifier. No per-route metrics or alarms.

**Tech Stack:** Python 3 (CloudWatch Synthetics runtime `syn-python-selenium-5.1`, stdlib `urllib`), pytest, PyYAML (tests only), Terraform.

**Spec:** `docs/superpowers/specs/2026-11-17-multi-route-checks-design.md`

## Global Constraints

- Canary code is identical in every environment; only `terraform/config/<env>/` differs.
- Handler filenames use underscores: `handler: http_checks.handler`.
- Canary name (`${environment}-${name}` with `_` replaced by `-`) must be at most 21 characters.
- `http_checks`: `schedule: rate(1 minute)`, alarm 2 datapoints of 2, `alarm.period_seconds: 60`, response plan `default`.
- `ui_journey`: `schedule: rate(30 minutes)`, alarm 2 of 2, `alarm.period_seconds: 1800`, response plan `partner`.
- Missing data stays `breaching` for canary alarms. Default period when `period_seconds` is absent stays 300.
- Request header `User-Agent: ss-canary` on every HTTP call. No cache-buster on either check.
- `/api/q` is `POST` with a JSON body from config; real body and response shape are placeholders until supplied.
- Failure message must name each failing route (`index.js`, `/api/q`).
- Do not touch CloudFront, ALB or OpenSearch alarms (`alarms.tf`).

## Review Focus

1. `/api/q` returns 200 with an empty or missing results list: must fail (a real search did not run).
2. `/api/q` returns 200 with an HTML error page instead of JSON: must fail, not crash with an unnamed exception.
3. `index.js` fails and `/api/q` passes (and the reverse): the API check still runs, and only the failing route is named; both failing names both.
4. A network error or timeout on one route: reported as that route's failure, and the other route still runs.
5. Malformed `API_BODY` env var: fails loudly with a clear message, never passes silently.

---

## File Structure

- Create `src/http_checks/config.yml`, `src/http_checks/python/http_checks.py`: the new canary.
- Delete `src/api_search/`.
- Modify `src/ui_journey/config.yml`: schedule, alarm period, response plan.
- Modify `terraform/manifests/main.tf`: per-canary alarm period.
- Modify `terraform/manifests/teams.tf`: Teams subscription for every response plan topic.
- Modify `terraform/config/dev/response_plans.yml`: add `partner`.
- Create `tests/conftest.py`, `tests/test_http_checks.py`, `tests/test_configs.py`, `tests/requirements.txt`.
- Modify `README.md`, `docs/monitoring-plan.md`.

---

### Task 1: `http_checks` handler

**Files:**
- Create: `src/http_checks/python/http_checks.py`
- Create: `tests/conftest.py` (puts `src/http_checks/python` on `sys.path`; stubs `aws_synthetics.common.synthetics_logger` with a `logging.getLogger("test")` in `sys.modules`)
- Create: `tests/requirements.txt` (`pytest`, `pyyaml`)
- Test: `tests/test_http_checks.py`

**Interfaces:**
- Produces:
  - `@dataclass Config(index_js_url: str, api_url: str, api_body: dict, max_latency_ms: int, index_js_min_bytes: int, results_key: str)`
  - `load_config(env: Mapping[str, str]) -> Config`. Reads `INDEX_JS_URL`, `API_URL`, `API_BODY` (JSON string), `MAX_LATENCY_MS` (default `"3000"`), `INDEX_JS_MIN_BYTES` (default `"1000"`), `API_RESULTS_KEY` (default `"results"`). Raises `ValueError("API_BODY is not valid JSON: ...")`.
  - `_request(method: str, url: str, body: bytes | None, timeout: float) -> tuple[int, dict[str, str], bytes, int]`. Returns status, lowercased headers, body bytes, elapsed ms. Returns the status for HTTP 4xx/5xx instead of raising. Sends `User-Agent: ss-canary`, plus `Content-Type: application/json` when a body is given.
  - `check_index_js(cfg: Config) -> None` and `check_api(cfg: Config) -> None`, each raising `Exception` with a message starting with its route name.
  - `run_checks(cfg: Config) -> None`: runs both, collects failures, raises one `Exception` joining messages with `"; "`.
  - `handler(event, context) -> None`: `run_checks(load_config(os.environ))`.

- [ ] **Step 1: Write failing tests** in `tests/test_http_checks.py`, patching `http_checks._request` with `monkeypatch`. Test names and assertions:
  - `test_all_pass`: index.js returns `(200, {"content-type": "application/javascript"}, b"x"*2000, 50)`, api returns `(200, {}, b'{"results":[{"id":1}]}', 80)`; `run_checks` returns without raising.
  - `test_index_js_wrong_content_type_fails`: content-type `text/html` raises with message containing `index.js`.
  - `test_index_js_too_small_fails`: body of 10 bytes raises `index.js`.
  - `test_index_js_slow_fails`: elapsed 5000 with max 3000 raises `index.js`.
  - `test_api_empty_results_fails`: body `{"results":[]}` raises `/api/q`.
  - `test_api_html_body_fails`: 200 with body `<html>` raises `/api/q` (no `JSONDecodeError` escapes).
  - `test_api_non_200_fails`: status 503 raises `/api/q` and the message contains `503`.
  - `test_api_posts_json_body`: asserts `_request` was called with method `"POST"` and a body equal to `json.dumps(cfg.api_body).encode()`.
  - `test_index_fails_api_passes_names_only_index_js`: message contains `index.js`, not `/api/q`.
  - `test_both_fail_names_both`: message contains both route names.
  - `test_network_error_on_one_route_still_runs_other`: `_request` raises `OSError` for index.js; the API check is still called; message names `index.js`.
  - `test_load_config_bad_body_raises`: `API_BODY="{nope"` raises `ValueError`.
  - `test_load_config_defaults`: defaults for latency, min bytes and results key.
  - `test_request_maps_http_error_to_status`: patch `urllib.request.urlopen` to raise `urllib.error.HTTPError` with code 503; `_request` returns status 503 instead of raising.

- [ ] **Step 2: Run to verify failure**

Run: `pip install -r tests/requirements.txt && pytest tests/test_http_checks.py -v`
Expected: FAIL (`ModuleNotFoundError: http_checks`).

- [ ] **Step 3: Implement the module** with the interfaces above. `check_api` must treat a missing or empty list at `cfg.results_key` as failure and catch `json.JSONDecodeError`. `run_checks` wraps each check in try/except `Exception`, appending the message (prefixing the route name if the exception came from `_request`, e.g. `index.js: request failed: <err>`).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_http_checks.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/http_checks tests/conftest.py tests/requirements.txt tests/test_http_checks.py
git commit -m "feat: add http_checks canary handler"
```

### Task 2: `http_checks` config, remove `api_search`, config validation

**Files:**
- Create: `src/http_checks/config.yml`
- Delete: `src/api_search/` (both files)
- Test: `tests/test_configs.py`

**Interfaces:**
- Consumes: handler path `http_checks.handler` from Task 1.
- Produces: `src/http_checks/config.yml` with keys `name: http-checks`, `handler: http_checks.handler`, `runtime_version: syn-python-selenium-5.1`, `schedule: rate(1 minute)`, `timeout_in_seconds: 30`, `memory_in_mb: 512`, `active_tracing: false`, retention days copied from the old `api_search` config, `environment_variables` (`INDEX_JS_URL: https://search.example.com/index.js`, `API_URL: https://search.example.com/api/q`, `API_BODY: '{"query": "example"}'`, `MAX_LATENCY_MS: "3000"`, `INDEX_JS_MIN_BYTES: "1000"`, `API_RESULTS_KEY: results`, all marked as placeholders in a comment), and `alarm: {response_plan: default, datapoints_to_alarm: 2, evaluation_periods: 2, period_seconds: 60}`.

- [ ] **Step 1: Write failing tests** in `tests/test_configs.py`, parametrised over every `src/*/config.yml`:
  - `test_required_keys`: has `name`, `handler`, `runtime_version`, `schedule`, `alarm` with `response_plan`, `datapoints_to_alarm`, `evaluation_periods`.
  - `test_name_fits_canary_limit`: `len("dev-" + name.replace("_", "-")) <= 21`.
  - `test_response_plan_exists`: `alarm.response_plan` is a key in `terraform/config/dev/response_plans.yml`.
  - `test_handler_file_exists`: `src/<dir>/python/<module>.py` exists for `handler: <module>.handler`.
  - `test_period_matches_schedule` (only when `period_seconds` is set): a `rate(N minute[s])` schedule has `period_seconds` that is a multiple of 60 and not less than the schedule interval.
  - `test_http_checks_is_one_minute_and_ui_journey_is_thirty` pinning the spec values for both.

- [ ] **Step 2: Run** `pytest tests/test_configs.py -v`. Expected: FAIL (`http_checks` dir missing, `partner` plan missing).

- [ ] **Step 3: Create `config.yml`** per the Produces block and `git rm -r src/api_search`.

- [ ] **Step 4: Run** `pytest tests/test_configs.py -v`. Expected: the `http_checks` cases PASS; `ui_journey` and `partner` cases still FAIL until Task 3.

- [ ] **Step 5: Commit**

```bash
git add src/http_checks/config.yml tests/test_configs.py
git commit -m "feat: add http_checks config and drop api_search"
```

### Task 3: Terraform and `ui_journey` changes

**Files:**
- Modify: `src/ui_journey/config.yml`, `terraform/config/dev/response_plans.yml`, `terraform/manifests/main.tf:149` and `teams.tf:68-87`

**Interfaces:**
- Consumes: `alarm.period_seconds` key from Task 2 (optional per canary).
- Produces: alarm `period = try(each.value.alarm.period_seconds, 300)`; `partner` plan key with the same email list as `default`; Teams permission and subscription for every plan topic.

- [ ] **Step 1: Confirm Task 2's remaining config tests fail** (`ui_journey` values, `partner` plan).

- [ ] **Step 2: Edit configs.** `ui_journey`: `schedule: rate(30 minutes)`, `alarm.period_seconds: 1800`, `alarm.response_plan: partner`. `response_plans.yml`: add `partner` with the same emails as `default`, with a comment that it is the lower-priority plan for the partner page.

- [ ] **Step 3: Edit `main.tf`**: replace `period = 300` with `period = try(each.value.alarm.period_seconds, 300)`.

- [ ] **Step 4: Edit `teams.tf`**: `aws_lambda_permission.sns` iterates over `aws_sns_topic.alerts` plus `cloudfront` when `enable_teams`, with `statement_id = "AllowSNS-${each.key}"`. Replace `aws_sns_topic_subscription.teams` with a `for_each` over `aws_sns_topic.alerts` (only when `enable_teams`). Teams was never applied (plan TODO), so no state moves are needed. Keep `aws_sns_topic_subscription.teams_cloudfront` unchanged.

- [ ] **Step 5: Verify**

Run: `pytest tests -v`
Expected: all PASS.
Run (if Terraform is installed; otherwise state in the commit that it was not run): `cd terraform/manifests && terraform fmt -check && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 6: Commit**

```bash
git add src/ui_journey/config.yml terraform
git commit -m "feat: per-canary alarm period, partner response plan, slower ui_journey"
```

### Task 4: Documentation

**Files:**
- Modify: `README.md`, `docs/monitoring-plan.md`

- [ ] **Step 1: Update docs** to match the spec: README canaries list (`http_checks`, `ui_journey`) and layout; plan canary table (cadences, runtimes), the four-row signal table from the spec (including the single-alarm note), `partner` plan under Notifications, the SLI note (99.9% from `http_checks` only), and the TODO list: replace the `api_search` JSON-shape item with `http_checks` real body and shape, mark `/ready` and in-VPC canary dropped, mark partner approval done, and add "verify the ALB health check touches OpenSearch".

- [ ] **Step 2: Verify no stale references**

Run: `grep -rn "api_search\|api-search" README.md docs src terraform`
Expected: no matches except inside `docs/superpowers/`.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/monitoring-plan.md
git commit -m "docs: update monitoring plan for multi-route checks"
```

## Self-Review Notes

- Spec coverage: canaries and cadences (Tasks 1, 2, 3), per-canary alarm period (3), `partner` plan with Teams (3), `api_search` replaced (2), signal table and SLI and doc updates (4). Per-route alarms, email formatting and in-VPC canary are non-goals and have no task.
- Open placeholders carried from the spec: real `/api/q` body, response shape, `index.js` minimum size. They are config values, not code gaps.
