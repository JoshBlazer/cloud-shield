"""Slack Block Kit message builder and direct webhook sender."""

import os
from typing import Any

import requests
import structlog

log = structlog.get_logger()

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
DASHBOARD_URL     = os.environ.get("DASHBOARD_URL", "https://cloudshield.example.com")

_EMOJI = {
    "CRITICAL": ":red_circle:",
    "HIGH":     ":large_orange_circle:",
    "MEDIUM":   ":large_yellow_circle:",
    "LOW":      ":white_circle:",
}


def _blocks_for_violation(v: dict[str, Any]) -> list[dict]:
    vid   = v.get("violation_id", v.get("pk", ""))
    sev   = v["severity"]
    emoji = _EMOJI.get(sev, ":white_circle:")
    team  = v.get("team", "untagged")

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{emoji} *{sev}* — {v['rule_name']}\n"
                    f"`{v['rule_id']}` · _{v['resource_type']}_"
                ),
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Resource:*\n`{v['resource_id']}`"},
                {"type": "mrkdwn", "text": f"*Team:*\n{team}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"_{v['reason']}_"}
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Dashboard"},
                    "url": f"{DASHBOARD_URL}/violations/{vid}",
                    "action_id": "open_dashboard",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Acknowledge"},
                    "style": "primary",
                    "action_id": "acknowledge",
                    "value": vid,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Snooze 7d"},
                    "action_id": "snooze",
                    "value": f"{vid}:7",
                },
            ],
        },
        {"type": "divider"},
    ]


def _post(payload: dict) -> None:
    if not SLACK_WEBHOOK_URL:
        log.warning("slack.webhook_not_configured")
        return
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.error("slack.post_failed", error=str(exc))


def send_new_violations(violations: list[dict[str, Any]]) -> None:
    """Fire Block Kit alerts for newly detected violations (batched 5 per message)."""
    if not violations:
        return

    for i in range(0, len(violations), 5):
        batch = violations[i : i + 5]
        blocks: list[dict] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"CloudShield: {len(violations)} new violation(s) detected",
                },
            }
        ]
        for v in batch:
            blocks.extend(_blocks_for_violation(v))

        _post({"blocks": blocks})
        log.info("slack.alerts_sent", batch_size=len(batch))


def send_resolutions(count: int) -> None:
    """Brief message when violations are auto-resolved."""
    if count == 0:
        return
    _post({
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":white_check_mark: *{count} violation(s) auto-resolved* "
                        f"— resources are now compliant."
                    ),
                },
            }
        ]
    })
    log.info("slack.resolutions_sent", count=count)
