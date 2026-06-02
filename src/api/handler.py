"""API Gateway Lambda — REST endpoints for the CloudShield dashboard."""

import json
import os
import re
from typing import Any

import boto3
import structlog

from src.engine.evaluator import run_audit
from src.store import violations as store

log = structlog.get_logger()

_CORS = {
    "Access-Control-Allow-Origin":  os.environ.get("DASHBOARD_ORIGIN", "*"),
    "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,X-Api-Key",
}


def _ok(body: Any, status: int = 200) -> dict:
    return {
        "statusCode": status,
        "headers": {**_CORS, "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _err(msg: str, status: int = 400) -> dict:
    return {
        "statusCode": status,
        "headers": {**_CORS, "Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }


def _session() -> Any:
    return boto3.Session()


# ── Route handlers ────────────────────────────────────────────────────────────

def _list_violations(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    items = store.list_violations(
        _session(),
        status=qs.get("status"),
        severity=qs.get("severity"),
        team=qs.get("team"),
        limit=int(qs.get("limit", 200)),
    )
    return _ok({"violations": items, "count": len(items)})


def _get_violation(event: dict, violation_id: str) -> dict:
    item = store.get_by_id(_session(), violation_id)
    if not item:
        return _err("violation not found", 404)
    return _ok(item)


def _patch_violation(event: dict, violation_id: str) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err("invalid JSON body")

    action = body.get("action")
    session = _session()

    if action == "acknowledge":
        ok = store.acknowledge(session, violation_id, by=body.get("by", "dashboard-user"))
    elif action == "snooze":
        ok = store.snooze(session, violation_id, days=int(body.get("days", 7)))
    elif action == "exempt":
        ok = store.exempt(session, violation_id, reason=body.get("reason", ""))
    else:
        return _err(f"unknown action '{action}'")

    if not ok:
        return _err("violation not found", 404)
    return _ok({"ok": True, "action": action, "violation_id": violation_id})


def _get_summary(event: dict) -> dict:
    return _ok(store.get_summary(_session()))


def _trigger_audit(event: dict) -> dict:
    result = run_audit()
    return _ok({
        "resources_audited": result["resources_audited"],
        "violations_found": len(result["violations"]),
    })


def _slack_interact(event: dict) -> dict:
    """Handle Slack interactivity callback (button clicks)."""
    import urllib.parse

    raw = event.get("body", "")
    parsed = urllib.parse.parse_qs(raw)
    payload_str = parsed.get("payload", ["{}"])[0]
    payload = json.loads(payload_str)

    actions = payload.get("actions", [])
    session = _session()

    for action in actions:
        action_id = action.get("action_id", "")
        value     = action.get("value", "")

        if action_id == "acknowledge":
            user = payload.get("user", {}).get("name", "slack-user")
            store.acknowledge(session, value, by=user)
        elif action_id == "snooze":
            vid, days = value.split(":") if ":" in value else (value, "7")
            store.snooze(session, vid, days=int(days))

    return _ok({"ok": True})


# ── Router ────────────────────────────────────────────────────────────────────

_ROUTES: list[tuple[str, str, Any]] = [
    ("GET",   r"^/violations$",                    _list_violations),
    ("GET",   r"^/violations/(?P<id>[^/]+)$",      _get_violation),
    ("PATCH", r"^/violations/(?P<id>[^/]+)$",      _patch_violation),
    ("GET",   r"^/summary$",                       _get_summary),
    ("POST",  r"^/audit/trigger$",                 _trigger_audit),
    ("POST",  r"^/slack/interact$",                _slack_interact),
]


def api_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("httpMethod", "GET")
    path   = event.get("path", "/")

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": _CORS, "body": ""}

    for http_method, pattern, fn in _ROUTES:
        if method != http_method:
            continue
        m = re.match(pattern, path)
        if not m:
            continue

        groups = m.groupdict()
        try:
            if "id" in groups:
                return fn(event, groups["id"])
            return fn(event)
        except Exception as exc:  # noqa: BLE001
            log.error("api.unhandled_error", path=path, error=str(exc))
            return _err("internal server error", 500)

    return _err(f"no route for {method} {path}", 404)
