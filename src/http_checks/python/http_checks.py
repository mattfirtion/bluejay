import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Optional

from aws_synthetics.common import synthetics_logger as logger

REQUEST_TIMEOUT_S = 10


@dataclass
class Config:
    index_js_url: str
    api_url: str
    api_body: dict
    max_latency_ms: int
    index_js_min_bytes: int
    results_key: str


def load_config(env: Mapping[str, str]) -> Config:
    try:
        api_body = json.loads(env["API_BODY"])
    except ValueError as e:
        raise ValueError(f"API_BODY is not valid JSON: {e}") from e
    return Config(
        index_js_url=env["INDEX_JS_URL"],
        api_url=env["API_URL"],
        api_body=api_body,
        max_latency_ms=int(env.get("MAX_LATENCY_MS", "3000")),
        index_js_min_bytes=int(env.get("INDEX_JS_MIN_BYTES", "1000")),
        results_key=env.get("API_RESULTS_KEY", "results"),
    )


def _request(method: str, url: str, body: Optional[bytes], timeout: float):
    headers = {"User-Agent": "ss-canary"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, resp_headers, data = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        status, resp_headers, data = e.code, e.headers or {}, b""
    elapsed_ms = int((time.time() - start) * 1000)
    lowered = {k.lower(): v for k, v in dict(resp_headers).items()}
    logger.info("%s %s -> %s in %sms", method, url, status, elapsed_ms)
    return status, lowered, data, elapsed_ms


def check_index_js(cfg: Config) -> None:
    status, headers, body, elapsed_ms = _request("GET", cfg.index_js_url, None, REQUEST_TIMEOUT_S)
    if status != 200:
        raise Exception(f"index.js: unexpected status {status}")
    if "javascript" not in headers.get("content-type", ""):
        raise Exception(f"index.js: unexpected content-type {headers.get('content-type')!r}")
    if len(body) < cfg.index_js_min_bytes:
        raise Exception(f"index.js: body too small ({len(body)} < {cfg.index_js_min_bytes} bytes)")
    if elapsed_ms > cfg.max_latency_ms:
        raise Exception(f"index.js: too slow ({elapsed_ms}ms > {cfg.max_latency_ms}ms)")


def check_api(cfg: Config) -> None:
    payload = json.dumps(cfg.api_body).encode()
    status, _headers, body, elapsed_ms = _request("POST", cfg.api_url, payload, REQUEST_TIMEOUT_S)
    if status != 200:
        raise Exception(f"/api/q: unexpected status {status}")
    if elapsed_ms > cfg.max_latency_ms:
        raise Exception(f"/api/q: too slow ({elapsed_ms}ms > {cfg.max_latency_ms}ms)")
    try:
        data = json.loads(body)
    except ValueError as e:
        raise Exception(f"/api/q: response is not JSON ({e})") from e
    results = data.get(cfg.results_key) if isinstance(data, dict) else None
    if not results:
        raise Exception(f"/api/q: no {cfg.results_key!r} in response (search did not run)")


def run_checks(cfg: Config) -> None:
    failures = []
    for route, check in (("index.js", check_index_js), ("/api/q", check_api)):
        try:
            check(cfg)
        except Exception as e:
            message = str(e)
            failures.append(message if message.startswith(route) else f"{route}: request failed: {e}")
    if failures:
        raise Exception("; ".join(failures))


def handler(event, context):
    run_checks(load_config(os.environ))
