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

from src.config import secrets
from src.store import audit_log
from src.store import violations as store

log = structlog.get_logger()

# Secrets (api_key, slack_signing_secret) come from Secrets Manager via the
# secrets module — never from Lambda env vars. Non-secret config stays in env.
_AUDITOR_FUNCTION  = os.environ.get("AUDITOR_FUNCTION_NAME", "")
_COGNITO_ISSUER    = os.environ.get("COGNITO_ISSUER", "")
_COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")

_ALLOWED_ORIGINS: set[str] = {
    o for o in (
        os.environ.get("DASHBOARD_URL", "").rstrip("/"),
        "http://localhost:3000",
        "http://localhost:4173",
        "http://localhost:5173",
    ) if o
}

# Module-level JWKS cache — persists across warm invocations, refreshed on a TTL
# so a long-lived container picks up Cognito signing-key rotation.
_JWKS_CACHE: dict = {}
_JWKS_FETCHED_AT: float = 0.0
_JWKS_TTL = 3600  # seconds


# ── Event parsing ─────────────────────────────────────────────────────────────

def _parse_event(event: dict) -> tuple[str, str, dict[str, str]]:
    """Support payload format 1.0 (httpMethod/path) and 2.0 (requestContext.http/rawPath)."""
    rc       = event.get("requestContext", {})
    http_ctx = rc.get("http", {})
    method = (http_ctx.get("method") or event.get("httpMethod") or "GET").upper()
    path   = event.get("rawPath") or event.get("path") or "/"
    raw    = event.get("headers", {}) or {}
    headers = {k.lower(): v for k, v in raw.items()}
    return method, path, headers


# ── Auth ──────────────────────────────────────────────────────────────────────

def _load_jwks(force: bool = False) -> dict:
    """Fetch the Cognito JWKS, cached with a TTL. force=True bypasses the cache."""
    global _JWKS_CACHE, _JWKS_FETCHED_AT
    now = time.time()
    if not force and _JWKS_CACHE and (now - _JWKS_FETCHED_AT) < _JWKS_TTL:
        return _JWKS_CACHE
    import urllib.request
    url = f"{_COGNITO_ISSUER}/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310
        _JWKS_CACHE = json.loads(r.read())
        _JWKS_FETCHED_AT = now
    return _JWKS_CACHE


def _verify_jwt(token: str) -> bool:
    if not _COGNITO_ISSUER or not _COGNITO_CLIENT_ID:
        return False
    try:
        from jose import jwt as jose_jwt

        # If the token's signing key isn't in the cached JWKS, force a refresh —
        # this is how key rotation is picked up before the TTL elapses.
        kid  = jose_jwt.get_unverified_header(token).get("kid")
        jwks = _load_jwks()
        if kid and kid not in {k.get("kid") for k in jwks.get("keys", [])}:
            jwks = _load_jwks(force=True)

        # Validate signature + issuer here. Cognito ACCESS tokens have no `aud`
        # claim (they carry `client_id`), so audience is checked per token_use
        # below rather than via jose's audience= (which assumes an `aud` claim).
        claims = jose_jwt.decode(
            token, jwks,
            algorithms=["RS256"],
            issuer=_COGNITO_ISSUER,
            options={"verify_aud": False},
        )
        token_use = claims.get("token_use")
        if token_use == "id":
            return claims.get("aud") == _COGNITO_CLIENT_ID
        if token_use == "access":
            return claims.get("client_id") == _COGNITO_CLIENT_ID
        return False
    except Exception:  # noqa: BLE001
        return False


def _is_authorized(headers: dict[str, str]) -> bool:
    """Accept API key (machine-to-machine) OR Cognito JWT Bearer token (dashboard)."""
    api_key = secrets.get_secret("api_key")

    # API key — constant-time to prevent timing oracle
    if api_key:
        provided = headers.get("x-api-key", "")
        if provided and hmac.compare_digest(provided, api_key):
            return True

    # Cognito JWT Bearer
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer ") and _verify_jwt(auth[7:]):
        return True

    # Neither API key nor Cognito configured → dev/local mode, pass through
    return not (api_key or _COGNITO_ISSUER)


def _verify_slack_signature(event: dict, headers: dict[str, str]) -> bool:
    signing_secret = secrets.get_secret("slack_signing_secret")
    if not signing_secret:
        return True
    timestamp  = headers.get("x-slack-request-timestamp", "")
    sig_header = headers.get("x-slack-signature", "")
    if not timestamp or not sig_header:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    body     = event.get("body", "") or ""
    sig_base = f"v0:{timestamp}:{body}"
    mac      = hmac.new(signing_secret.encode(), sig_base.encode(), hashlib.sha256)
    return hmac.compare_digest("v0=" + mac.hexdigest(), sig_header)


# ── Response helpers ──────────────────────────────────────────────────────────

def _cors(origin: str) -> dict[str, str]:
    allowed = origin if origin in _ALLOWED_ORIGINS else next(iter(_ALLOWED_ORIGINS), "*")
    return {
        "Access-Control-Allow-Origin":  allowed,
        "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,X-Api-Key,Authorization",
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
    origin = event.get("_origin", "")
    item   = store.get_by_id(_session(), violation_id)
    if not item:
        return _err("violation not found", 404, origin=origin)
    return _ok(item, origin=origin)


def _get_violation_history(event: dict, violation_id: str) -> dict:
    origin = event.get("_origin", "")
    events = audit_log.get_history(_session(), violation_id)
    return _ok({"violation_id": violation_id, "events": events}, origin=origin)


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
    origin = event.get("_origin", "")
    if not _AUDITOR_FUNCTION:
        return _err("AUDITOR_FUNCTION_NAME not configured", 500, origin=origin)
    boto3.client("lambda").invoke(
        FunctionName=_AUDITOR_FUNCTION,
        InvocationType="Event",
        Payload=b"{}",
    )
    return _ok({"triggered": True, "message": "Audit queued"}, 202, origin=origin)


def _slack_interact(event: dict, headers: dict[str, str]) -> dict:
    import urllib.parse
    if not _verify_slack_signature(event, headers):
        return _err("invalid Slack signature", 401)

    raw     = event.get("body", "")
    parsed  = urllib.parse.parse_qs(raw)
    payload = json.loads(parsed.get("payload", ["{}"])[0])
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
    ("GET",   r"^/violations$",                         _list_violations),
    # history before bare /{id} so the more specific pattern wins
    ("GET",   r"^/violations/(?P<id>[^/]+)/history$",   _get_violation_history),
    ("GET",   r"^/violations/(?P<id>[^/]+)$",           _get_violation),
    ("PATCH", r"^/violations/(?P<id>[^/]+)$",           _patch_violation),
    ("GET",   r"^/summary$",                            _get_summary),
    ("POST",  r"^/audit/trigger$",                      _trigger_audit),
    ("POST",  r"^/slack/interact$",                     _slack_interact),
]


def api_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, path, headers = _parse_event(event)
    origin = headers.get("origin", "")

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": _cors(origin), "body": ""}

    if not _is_authorized(headers):
        return _err("unauthorized", 401, origin=origin)

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
