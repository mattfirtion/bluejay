import json
import os
import urllib.request

import boto3

_webhook_url = None


def _get_webhook_url():
    global _webhook_url
    if _webhook_url is None:
        sm = boto3.client("secretsmanager")
        _webhook_url = sm.get_secret_value(SecretId=os.environ["WEBHOOK_SECRET_ARN"])["SecretString"].strip()
    return _webhook_url


def _card(alarm):
    state = alarm.get("NewStateValue", "UNKNOWN")
    color = {"ALARM": "Attention", "OK": "Good"}.get(state, "Warning")
    facts = [
        ("State", f"{alarm.get('OldStateValue', '?')} -> {state}"),
        ("Region", alarm.get("Region", "")),
        ("Time", alarm.get("StateChangeTime", "")),
        ("Reason", alarm.get("NewStateReason", "")),
    ]
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "color": color,
                     "text": f"{state}: {alarm.get('AlarmName', 'CloudWatch alarm')}", "wrap": True},
                    {"type": "TextBlock", "text": alarm.get("AlarmDescription") or "", "wrap": True,
                     "isVisible": bool(alarm.get("AlarmDescription"))},
                    {"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in facts]},
                ],
            },
        }],
    }


def handler(event, context):
    for record in event["Records"]:
        message = record["Sns"]["Message"]
        try:
            payload = _card(json.loads(message))
        except ValueError:  # not a CloudWatch alarm JSON; forward as plain text
            payload = {"type": "message", "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                            "type": "AdaptiveCard", "version": "1.4",
                            "body": [{"type": "TextBlock", "text": message, "wrap": True}]}}]}
        req = urllib.request.Request(
            _get_webhook_url(),
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                raise Exception(f"Teams webhook returned {resp.status}")
