import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = sorted((ROOT / "src").glob("*/config.yml"))
PLANS = yaml.safe_load((ROOT / "terraform/config/response_plans.yml").read_text())


def load(path):
    return yaml.safe_load(path.read_text())


def ids(paths):
    return [p.parent.name for p in paths]


@pytest.mark.parametrize("path", CONFIGS, ids=ids(CONFIGS))
def test_required_keys(path):
    cfg = load(path)
    for key in ("name", "handler", "runtime_version", "schedule", "alarm"):
        assert key in cfg
    for key in ("response_plan", "datapoints_to_alarm", "evaluation_periods"):
        assert key in cfg["alarm"]


@pytest.mark.parametrize("path", CONFIGS, ids=ids(CONFIGS))
def test_name_fits_canary_limit(path):
    name = load(path)["name"]
    assert len("dev-" + name.replace("_", "-")) <= 21


@pytest.mark.parametrize("path", CONFIGS, ids=ids(CONFIGS))
def test_response_plan_exists(path):
    assert load(path)["alarm"]["response_plan"] in PLANS


@pytest.mark.parametrize("path", CONFIGS, ids=ids(CONFIGS))
def test_handler_file_exists(path):
    module = load(path)["handler"].split(".")[0]
    assert (path.parent / "python" / f"{module}.py").exists()


@pytest.mark.parametrize("path", CONFIGS, ids=ids(CONFIGS))
def test_period_matches_schedule(path):
    cfg = load(path)
    period = cfg["alarm"].get("period_seconds")
    if period is None:
        pytest.skip("no period_seconds set")
    m = re.fullmatch(r"rate\((\d+) (minute|minutes)\)", cfg["schedule"])
    assert m, cfg["schedule"]
    assert period % 60 == 0
    assert period >= int(m.group(1)) * 60


def test_http_checks_is_one_minute():
    cfg = load(ROOT / "src/http_checks/config.yml")
    assert cfg["schedule"] == "rate(1 minute)"
    assert cfg["handler"] == "http_checks.handler"
    assert cfg["alarm"] == {
        "response_plan": "default",
        "datapoints_to_alarm": 2,
        "evaluation_periods": 2,
        "period_seconds": 60,
    }


def test_ui_journey_is_thirty_minutes_on_partner_plan():
    cfg = load(ROOT / "src/ui_journey/config.yml")
    assert cfg["schedule"] == "rate(30 minutes)"
    assert cfg["alarm"]["period_seconds"] == 1800
    assert cfg["alarm"]["response_plan"] == "partner"
    assert cfg["alarm"]["datapoints_to_alarm"] == 2
    assert cfg["alarm"]["evaluation_periods"] == 2


def test_api_search_removed():
    assert not (ROOT / "src/api_search").exists()
