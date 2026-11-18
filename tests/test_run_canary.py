import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run_canary", ROOT / "scripts" / "run_canary.py")
run_canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_canary)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Minimal repo: one canary plus per-env overrides."""
    src = tmp_path / "src" / "demo_check"
    (src / "python").mkdir(parents=True)
    (src / "python" / "demo_check.py").write_text("def handler(e, c): pass\n")
    (src / "config.yml").write_text(
        yaml.safe_dump(
            {
                "name": "demo-check",
                "handler": "demo_check.handler",
                "schedule": "rate(1 minute)",
                "timeout_in_seconds": 30,
                "memory_in_mb": 512,
                "environment_variables": {"URL": "https://base", "MAX": "3000"},
                "alarm": {"response_plan": "default", "period_seconds": 60},
            }
        )
    )
    (tmp_path / "terraform" / "config" / "prod").mkdir(parents=True)
    (tmp_path / "terraform" / "config" / "prod" / "overrides.yml").write_text(
        yaml.safe_dump(
            {
                "canaries": {
                    "demo_check": {
                        "schedule": "rate(5 minutes)",
                        "environment_variables": {"URL": "https://prod"},
                        "alarm": {"period_seconds": 300},
                    }
                }
            }
        )
    )
    (tmp_path / "terraform" / "config" / "dev").mkdir(parents=True)
    (tmp_path / "terraform" / "config" / "dev" / "overrides.yml").write_text("canaries: {}\n")
    monkeypatch.setattr(run_canary, "ROOT", tmp_path)
    monkeypatch.setenv("SYNTHETICS_LAMBDA_RUNTIME", "python3.11")
    monkeypatch.setenv("SYNTHETICS_LAYER_ARN", "arn:aws:lambda:us-east-1:1:layer:L:1")
    monkeypatch.setenv("SMOKE_ARTIFACT_BUCKET", "bucket")
    return tmp_path


def test_override_replaces_scalars_and_merges_maps(repo):
    cfg = run_canary.merged_config("demo_check", "prod")
    assert cfg["schedule"] == "rate(5 minutes)"
    assert cfg["environment_variables"] == {"URL": "https://prod", "MAX": "3000"}
    assert cfg["alarm"] == {"response_plan": "default", "period_seconds": 300}


def test_env_without_overrides_uses_base(repo):
    cfg = run_canary.merged_config("demo_check", "dev")
    assert cfg["schedule"] == "rate(1 minute)"
    assert cfg["environment_variables"]["URL"] == "https://base"


def test_env_without_overrides_file_uses_base(repo):
    cfg = run_canary.merged_config("demo_check", "staging")
    assert cfg["environment_variables"]["URL"] == "https://base"


def test_prepare_writes_template_and_event(repo):
    out = run_canary.prepare("demo_check", "prod", repo / "build" / "sam" / "demo_check")
    template = yaml.safe_load((out / "template.yml").read_text())
    props = template["Resources"]["Canary"]["Properties"]
    assert props["Runtime"] == "python3.11"
    assert props["Layers"] == ["arn:aws:lambda:us-east-1:1:layer:L:1"]
    assert props["Environment"]["Variables"]["URL"] == "https://prod"
    assert props["MemorySize"] == 512
    assert (out / "src" / "demo_check.py").exists()

    event = json.loads((out / "event.json").read_text())
    assert event["customerCanaryHandlerName"] == "demo_check.handler"
    assert event["artifactS3Location"]["s3Bucket"] == "bucket"
    assert event["canaryName"] == "smoke-demo-check-prod"


def test_canary_name_fits_limit_and_has_no_underscores(repo):
    out = run_canary.prepare("demo_check", "staging", repo / "build" / "x")
    name = json.loads((out / "event.json").read_text())["canaryName"]
    assert len(name) <= 21
    assert "_" not in name


def test_load_env_local_does_not_override_real_env(repo, monkeypatch):
    (repo / ".env.local").write_text("# c\nA_NEW=1\nSYNTHETICS_LAMBDA_RUNTIME=ignored\nQUOTED=\"x y\"\n")
    monkeypatch.delenv("A_NEW", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    run_canary.load_env_local()
    assert run_canary.os.environ["A_NEW"] == "1"
    assert run_canary.os.environ["QUOTED"] == "x y"
    assert run_canary.os.environ["SYNTHETICS_LAMBDA_RUNTIME"] == "python3.11"
