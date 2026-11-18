#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Run a canary locally in the real Synthetics runtime (SAM + Docker) against one environment.

    scripts/run_canary.py <canary> <env> [--prepare-only]

Settings are merged exactly like terraform/manifests/main.tf: src/<canary>/config.yml, then
terraform/config/<env>/overrides.yml (environment_variables merge key by key, other keys replace).
Nothing is deployed. Needs: Docker, AWS SAM CLI, AWS credentials, and these variables
(environment or a git-ignored .env.local, see .env.local.example):

    SYNTHETICS_LAYER_ARN       runtime layer for the canary's runtime_version in this region
                               (https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Synthetics_Debug_Locally.html)
    SYNTHETICS_LAMBDA_RUNTIME  Lambda runtime matching that layer, e.g. python3.11
    SMOKE_ARTIFACT_BUCKET      S3 bucket for screenshots/HAR (optional, errors are logged without it)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_env_local() -> None:
    """Load KEY=VALUE lines from .env.local (git-ignored) without overriding the real environment."""
    f = ROOT / ".env.local"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def merged_config(canary: str, env: str) -> dict:
    base = yaml.safe_load((ROOT / "src" / canary / "config.yml").read_text())
    overrides_file = ROOT / "terraform" / "config" / env / "overrides.yml"
    overrides = (yaml.safe_load(overrides_file.read_text()) or {}) if overrides_file.exists() else {}
    ov = (overrides.get("canaries") or {}).get(canary) or {}
    cfg = {**base, **ov}
    for key in ("environment_variables", "alarm"):
        cfg[key] = {**base.get(key, {}), **ov.get(key, {})}
    return cfg


def prepare(canary: str, env: str, out: Path) -> Path:
    cfg = merged_config(canary, env)
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(ROOT / "src" / canary / "python", out / "src", ignore=shutil.ignore_patterns("__pycache__"))

    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Transform": "AWS::Serverless-2016-10-31",
        "Resources": {
            "Canary": {
                "Type": "AWS::Serverless::Function",
                "Properties": {
                    "Handler": "cw-synthetics.handler",  # provided by the layer; runs customerCanaryHandlerName
                    "Runtime": os.environ["SYNTHETICS_LAMBDA_RUNTIME"],
                    "Architectures": ["x86_64"],
                    "CodeUri": "src/",
                    "MemorySize": cfg["memory_in_mb"],
                    "Timeout": cfg["timeout_in_seconds"],
                    "Environment": {"Variables": {k: str(v) for k, v in cfg["environment_variables"].items()}},
                    "Layers": [os.environ["SYNTHETICS_LAYER_ARN"]],
                },
            }
        },
    }
    (out / "template.yml").write_text(yaml.safe_dump(template, sort_keys=False))

    event = {
        # Distinct name so local runs never mix with the deployed canary's metrics.
        "canaryName": f"smoke-{canary}-{env}"[:21].replace("_", "-"),
        "artifactS3Location": {
            "s3Bucket": os.environ.get("SMOKE_ARTIFACT_BUCKET", "none"),
            "s3Key": f"smoke/{canary}/{env}",
        },
        "customerCanaryHandlerName": cfg["handler"],
        "canaryRunId": str(uuid.uuid4()),
    }
    (out / "event.json").write_text(json.dumps(event, indent=2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("canary")
    ap.add_argument("env")
    ap.add_argument("--prepare-only", action="store_true", help="write template/event and stop")
    args = ap.parse_args()
    load_env_local()

    out = prepare(args.canary, args.env, ROOT / "build" / "sam" / args.canary)
    if args.prepare_only:
        print(f"prepared {out}")
        return 0

    subprocess.run(["sam", "build", "--template", "template.yml"], cwd=out, check=True)
    proc = subprocess.run(
        ["sam", "local", "invoke", "Canary", "-e", "event.json"],
        cwd=out, capture_output=True, text=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    # `sam local invoke` can exit 0 on a function error, so also inspect the response.
    failed = proc.returncode != 0 or '"errorMessage"' in proc.stdout or "Traceback" in proc.stderr
    print(f"\n{'FAILED' if failed else 'PASSED'}: {args.canary} against {args.env}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
