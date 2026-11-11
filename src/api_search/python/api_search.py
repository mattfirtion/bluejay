import json
import os
import time
import urllib.request
import uuid

from aws_synthetics.common import synthetics_logger as logger

URL = os.environ["API_URL"]
MAX_LATENCY_MS = int(os.environ.get("MAX_LATENCY_MS", "3000"))


def main():
    # Unique query string so CloudFront cannot answer from cache.
    url = f"{URL}{'&' if '?' in URL else '?'}cb={uuid.uuid4().hex}"
    req = urllib.request.Request(url, headers={"User-Agent": "ss-canary"})

    start = time.time()
    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.status
        body = resp.read()
    elapsed_ms = int((time.time() - start) * 1000)
    logger.info("GET %s -> %s in %sms", url, status, elapsed_ms)

    if status != 200:
        raise Exception(f"Unexpected status {status}")
    if elapsed_ms > MAX_LATENCY_MS:
        raise Exception(f"Too slow: {elapsed_ms}ms > {MAX_LATENCY_MS}ms")
    # TODO: once the real API exists, assert the JSON shape, e.g. a "results" list.
    if body.lstrip()[:1] in (b"{", b"["):
        json.loads(body)


def handler(event, context):
    return main()
