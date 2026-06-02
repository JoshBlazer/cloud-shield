"""API Gateway Lambda — REST endpoints for the CloudShield dashboard."""

import hashlib
import hmac
import json
import os
import re
import time
from typing import Any

import boto3
import structlog

from src.store import violations as store

log = structlog.get_logger()

# Optional API key — if set, every non-OPTIONS request must carry X-Api-Key
_API_KEY            = os.environ.get("API_KEY", "")
_SLACK_SIGNING_SEC  = os.environ.get("SLACK_SIGNING_SECRET", "")
_AUDITOR_FUNCTION   = os.environ.get("AUDITOR_FUNCTION_NAME", "")

_ALLOWED_ORIGINS: set[str] = {
    o for o in (
        os.environ.get("DASHBOARD_URL", "").rstrip("/"),
        "http://localhost:3000",
        "http://localhost:4173",
    ) if o
}


# ── Event parsing ─────────────────────────────────────────────────────────────

def _parse_event(event: dict) -> tuple[str, str, dict[str, str]]:
    """Support payload format 1.0 (REST/httpMethod) and 2.0 (HTTP API/requestContext)."""
    rc       = event.get("requestContext", {})
    http_ctx = rc.get("http", {})

    method = (
        http_ctx.get("method")      # payload 2.0
        or event.get("httpMethod")  # payload 1.0
        or "GET"
    ).upper()

    path = (
        event.get("rawPath")        # payload 2.0
        or event.get("path")        # payload 1.0
        or "/"
    )

    # Normalize header names — HTTP/2 sends lowercase, REST API sends mixed-case
    raw_headers: dict[str, str] = event.get("headers", {}) or {}
    headers = {k.lower(): v for k, v in raw_headers.items()}

    return method, path, headers


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _is_authorized(headers: dict[str, str]) -> bool:
    """Constant-time API key check. Passes through when no key is configured."""
    if not _API_KEY:
        return True
    provided = headers.get("x-api-key", "")
    return bool(provided) and hmac.compare_digest(provided, _API_KEY)


def _verify_slack_signature(event: dict, headers: dict[str, str]) -> bool:
    """Verify Slack signing secret to block spoofed button callbacks."""
    if not _SLACK_SIGNING_SEC:
        return True
    timestamp  = headers.get("x-slack-request-timestamp", "")
    sig_header = headers.get("x-slack-signature", "")
    if not timestamp or not sig_header:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False  # outside 5-minute replay window
    except ValueError:
        return False
    body     = event.get("body", "") or ""
    sig_base = f"v0:{timestamp}:{body}"
    mac      = hmac.new(_SLACK_SIGNING_SEC.encode(), sig_base.encode(), hashlib.sha256)
    expected = "v0=" + mac.hexdigest()
    return hmac.compare_digest(expected, sig_header)


# ── Response helpers ──────────────────────────────────────────────────────────

def _cors(origin: str) -> dict[str, str]:
    allowed = origin if origin in _ALLOWED_ORIGINS else next(iter(_ALLOWED_ORIGINS), "*")
    return {
        "Access-Control-Allow-Origin":  allowed,
        "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,X-Api-Key",
    }


def _ok(body: Any, status: int = 200, origin: str = "") -> dict:
    return {
        "statusCode": status,
        "headers": {**_cors(origin), "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _err(msg: str, status: int = 400, origin: str = "") -> dict:
    return {
        "statusCode": status,
        "headers": {**_cors(origin), "Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }


def _session() -> Any:
    return boto3.Session()


# ── Route handlers ────────────────────────────────────────────────────────────

def _list_violations(event: dict, **_: Any) -> dict:
    qs = event.get("queryStringParameters") or {}
    try:
        limit = max(1, min(500, int(qs.get("limit", 200))))
    except (ValueError, TypeError):
        limit = 200
    items = store.list_violations(
        _session(),
        status=qs.get("status"),
        severity=qs.get("severity"),
        team=qs.get("team"),
        limit=limit,
    )
    return _ok({"violations": items, "count": len(items)}, origin=event.get("_origin", ""))


def _get_violation(event: dict, violation_id: str) -> dict:
    item = store.get_by_id(_session(), violation_id)
    if not item:
        return _err("violation not found", 404, origin=event.get("_origin", ""))
    return _ok(item, origin=event.get("_origin", ""))


def _patch_violation(event: dict, violation_id: str) -> dict:
    origin = event.get("_origin", "")
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err("invalid JSON body", origin=origin)

    action  = body.get("action")
    session = _session()

    if action == "acknowledge":
        ok = store.acknowledge(session, violation_id, by=body.get("by", "dashboard-user"))
    elif action == "snooze":
        ok = store.snooze(session, violation_id, days=int(body.get("days", 7)))
    elif action == "exempt":
        ok = store.exempt(session, violation_id, reason=body.get("reason", ""))
    else:
        return _err(f"unknown action '{action}'", origin=origin)

    if not ok:
        return _err("violation not found", 404, origin=origin)
    return _ok({"ok": True, "action": action, "violation_id": violation_id}, origin=origin)


def _get_summary(event: dict, **_: Any) -> dict:
    return _ok(store.get_summary(_session()), origin=event.get("_origin", ""))


def _trigger_audit(event: dict, **_: Any) -> dict:
    """Fire the auditor Lambda asynchronously — returns 202 immediately."""
    origin = event.get("_origin", "")
    if not _AUDITOR_FUNCTION:
        return _err("AUDITOR_FUNCTION_NAME not configured", 500, origin=origin)
    boto3.client("lambda").invoke(
        FunctionName=_AUDITOR_FUNCTION,
        InvocationType="Event",  # async — Lambda queues and returns 202
        Payload=b"{}",
    )
    return _ok({"triggered": True, "message": "Audit queued"}, 202, origin=origin)


def _slack_interact(event: dict, headers: dict[str, str]) -> dict:
    """Handle Slack interactivity callbacks (Acknowledge / Snooze buttons)."""
    import urllib.parse

    if not _verify_slack_signature(event, headers):
        return _err("invalid Slack signature", 401)

    raw    = event.get("body", "")
    parsed = urllib.parse.parse_qs(raw)
    payload_str = parsed.get("payload", ["{}"])[0]
    payload = json.loads(payload_str)

    session = _session()
    for action in payload.get("actions", []):
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
    ("GET",   r"^/violations$",               _list_violations),
    ("GET",   r"^/violations/(?P<id>[^/]+)$", _get_violation),
    ("PATCH", r"^/violations/(?P<id>[^/]+)$", _patch_violation),
    ("GET",   r"^/summary$",                  _get_summary),
    ("POST",  r"^/audit/trigger$",            _trigger_audit),
    ("POST",  r"^/slack/interact$",           _slack_interact),
]


def api_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, path, headers = _parse_event(event)
    origin = headers.get("origin", "")

    # CORS preflight — no auth required
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": _cors(origin), "body": ""}

    # Authenticate every other request (passthrough when API_KEY not set)
    if not _is_authorized(headers):
        return _err("unauthorized", 401, origin=origin)

    # Thread origin through so route handlers can include it in responses
    event["_origin"] = origin

    for http_method, pattern, fn in _ROUTES:
        if method != http_method:
            continue
        m = re.match(pattern, path)
        if not m:
            continue
        groups = m.groupdict()
        try:
            if http_method == "POST" and path == "/slack/interact":
                return fn(event, headers)
            if "id" in groups:
                return fn(event, groups["id"])
            return fn(event)
        except Exception as exc:  # noqa: BLE001
            log.error("api.unhandled_error", path=path, error=str(exc))
            return _err("internal server error", 500, origin=origin)

    return _err(f"no route for {method} {path}", 404, origin=origin)
