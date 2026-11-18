import re
from pathlib import Path

TEAMS_TF = (Path(__file__).resolve().parent.parent / "terraform/manifests/teams.tf").read_text()


def has_moved(from_addr, to_addr):
    pattern = (
        r"moved\s*\{\s*from\s*=\s*" + re.escape(from_addr) + r"\s*to\s*=\s*" + re.escape(to_addr) + r"\s*\}"
    )
    return re.search(pattern, TEAMS_TF) is not None


def test_teams_subscription_count_to_for_each_is_moved():
    assert has_moved(
        "aws_sns_topic_subscription.teams[0]",
        'aws_sns_topic_subscription.teams["default"]',
    )


def test_teams_lambda_permission_main_key_is_moved():
    assert has_moved(
        'aws_lambda_permission.sns["main"]',
        'aws_lambda_permission.sns["default"]',
    )
