"""DynamoDB violation store — CRUD and full lifecycle management."""

import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

log = structlog.get_logger()

TABLE_NAME = os.environ.get("VIOLATIONS_TABLE", "cloudshield-violations")

STATUS_OPEN         = "OPEN"
STATUS_ACKNOWLEDGED = "ACKNOWLEDGED"
STATUS_SNOOZED      = "SNOOZED"
STATUS_RESOLVED     = "RESOLVED"
STATUS_EXEMPTED     = "EXEMPTED"

ACTIVE_STATUSES = {STATUS_OPEN, STATUS_ACKNOWLEDGED, STATUS_SNOOZED}


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _table(session: Any):
    return session.resource("dynamodb").Table(TABLE_NAME)


def _pk(rule_id: str, resource_id: str) -> str:
    return f"{rule_id}#{resource_id}"


def _stable_id(rule_id: str, resource_id: str) -> str:
    """Deterministic UUID so the same violation always has the same ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{rule_id}#{resource_id}"))


# ── Write operations ──────────────────────────────────────────────────────────

def upsert_violation(
    session: Any,
    violation: dict[str, Any],
    tags: dict[str, str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """
    Idempotent, atomic violation write.

    Phase 1 — conditional create: succeeds only when the pk doesn't exist.
    Phase 2 — conditional update: bumps last_seen/occurrence if the item is
               ACTIVE or EXEMPTED. Exempted resources are re-detected every run
               but never re-alert (is_new stays False).
    Phase 3 — unconditional overwrite: reached only when the item exists in
               RESOLVED state, meaning the resource regressed after a fix.
               Returns is_new=True so the caller re-alerts.

    Returns (item, is_new). is_new=True triggers Slack + email alerts.
    """
    table      = _table(session)
    rule_id    = violation["rule_id"]
    resource_id = violation["resource_id"]
    pk         = _pk(rule_id, resource_id)
    now        = _now()

    new_item: dict[str, Any] = {
        "pk":             pk,
        "violation_id":   _stable_id(rule_id, resource_id),
        "rule_id":        rule_id,
        "rule_name":      violation["rule_name"],
        "severity":       violation["severity"],
        "resource_type":  violation["resource_type"],
        "resource_id":    resource_id,
        "reason":         violation["reason"],
        "status":         STATUS_OPEN,
        "first_detected": now,
        "last_seen":      now,
        "occurrence_count": 1,
        "resolved_at":    None,
        "acknowledged_by": None,
        "acknowledged_at": None,
        "snooze_until":   None,
        "exempt_reason":  None,
        "team":  violation.get("team") or (tags or {}).get("team", "untagged"),
        "owner": violation.get("owner") or (tags or {}).get("owner"),
        "region":     os.environ.get("AWS_REGION", "us-east-1"),
        "account_id": os.environ.get("AWS_ACCOUNT_ID", "unknown"),
    }

    # Phase 1: atomic create — only succeeds when pk is genuinely new
    try:
        table.put_item(
            Item=new_item,
            ConditionExpression=Attr("pk").not_exists(),
        )
        log.info("store.created", pk=pk)
        return new_item, True
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

    # Phase 2: item exists — bump occurrence if active or exempted (no re-alert)
    # EXEMPTED is included so deliberate exceptions survive re-audit without re-alerting.
    try:
        result = table.update_item(
            Key={"pk": pk},
            UpdateExpression="SET last_seen = :ls, occurrence_count = occurrence_count + :one",
            ConditionExpression=Attr("status").is_in(
                list(ACTIVE_STATUSES | {STATUS_EXEMPTED})
            ),
            ExpressionAttributeValues={":ls": now, ":one": 1},
            ReturnValues="ALL_NEW",
        )
        return result["Attributes"], False
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

    # Phase 3: item is RESOLVED — resource regressed, create fresh OPEN item
    table.put_item(Item=new_item)
    log.info("store.regression", pk=pk)
    return new_item, True


def acknowledge(session: Any, violation_id: str, by: str = "user") -> bool:
    item = get_by_id(session, violation_id)
    if not item:
        return False
    now = _now()
    _table(session).update_item(
        Key={"pk": item["pk"]},
        UpdateExpression="SET #s=:s, acknowledged_by=:by, acknowledged_at=:at",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": STATUS_ACKNOWLEDGED, ":by": by, ":at": now},
    )
    log.info("store.acknowledged", violation_id=violation_id, by=by)
    return True


def snooze(session: Any, violation_id: str, days: int = 7) -> bool:
    item = get_by_id(session, violation_id)
    if not item:
        return False
    until = (datetime.now(tz=UTC) + timedelta(days=days)).isoformat()
    _table(session).update_item(
        Key={"pk": item["pk"]},
        UpdateExpression="SET #s=:s, snooze_until=:u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": STATUS_SNOOZED, ":u": until},
    )
    log.info("store.snoozed", violation_id=violation_id, days=days)
    return True


def exempt(session: Any, violation_id: str, reason: str = "") -> bool:
    item = get_by_id(session, violation_id)
    if not item:
        return False
    _table(session).update_item(
        Key={"pk": item["pk"]},
        UpdateExpression="SET #s=:s, exempt_reason=:r",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": STATUS_EXEMPTED, ":r": reason},
    )
    log.info("store.exempted", violation_id=violation_id)
    return True


def mark_resolved(session: Any, pk: str) -> None:
    ttl = int(time.time()) + 90 * 86_400  # DynamoDB TTL: expire item 90 days after resolution
    try:
        _table(session).update_item(
            Key={"pk": pk},
            UpdateExpression="SET #s=:s, resolved_at=:r, #ttl=:ttl",
            ExpressionAttributeNames={"#s": "status", "#ttl": "ttl"},
            ExpressionAttributeValues={
                ":s": STATUS_RESOLVED,
                ":r": _now(),
                ":ttl": ttl,
            },
            ConditionExpression=Attr("status").is_in(list(ACTIVE_STATUSES)),
        )
        log.info("store.resolved", pk=pk)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def wake_snoozed_violations(session: Any) -> int:
    """
    Re-open any SNOOZED violations whose snooze_until has passed.
    Call this at the start of each audit run before evaluating resources.
    Returns the number of items flipped back to OPEN.
    """
    table = _table(session)
    now   = _now()
    woken = 0

    kwargs: dict[str, Any] = {
        "IndexName": "status-index",
        "KeyConditionExpression": Key("status").eq(STATUS_SNOOZED),
        "FilterExpression": Attr("snooze_until").lt(now),
        "ProjectionExpression": "pk",
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            try:
                table.update_item(
                    Key={"pk": item["pk"]},
                    UpdateExpression="SET #s = :open, snooze_until = :null",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":open": STATUS_OPEN, ":null": None},
                    ConditionExpression=Attr("status").eq(STATUS_SNOOZED),
                )
                woken += 1
                log.info("store.woken", pk=item["pk"])
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    return woken


# ── Read operations ───────────────────────────────────────────────────────────

def get_by_id(session: Any, violation_id: str) -> dict[str, Any] | None:
    resp = _table(session).query(
        IndexName="violation-id-index",
        KeyConditionExpression=Key("violation_id").eq(violation_id),
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def list_violations(
    session: Any,
    status: str | None = None,
    severity: str | None = None,
    team: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    table = _table(session)
    items: list[dict[str, Any]] = []

    if team:
        # team-index: paginate up to limit (team queries are user-scoped, cap is intentional)
        kwargs: dict[str, Any] = {
            "IndexName": "team-index",
            "KeyConditionExpression": Key("team").eq(team),
            "Limit": limit,
        }
        if status:
            kwargs["FilterExpression"] = Attr("status").eq(status)
        resp = table.query(**kwargs)
        items = resp.get("Items", [])

    elif status:
        # status-index: paginate all matching items
        kwargs = {
            "IndexName": "status-index",
            "KeyConditionExpression": Key("status").eq(status),
        }
        if severity:
            kwargs["FilterExpression"] = Attr("severity").eq(severity)
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp or len(items) >= limit:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        items = items[:limit]

    else:
        # Full scan — paginate across all pages
        kwargs = {}
        if severity:
            kwargs["FilterExpression"] = Attr("severity").eq(severity)
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp or len(items) >= limit:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        items = items[:limit]

    return items


def get_active_pks(session: Any) -> set[str]:
    """Return all PKs in an active (non-resolved/non-exempted) status, with pagination."""
    pks: set[str] = set()
    table = _table(session)
    for s in ACTIVE_STATUSES:
        kwargs: dict[str, Any] = {
            "IndexName": "status-index",
            "KeyConditionExpression": Key("status").eq(s),
            "ProjectionExpression": "pk",
        }
        while True:
            resp = table.query(**kwargs)
            pks.update(item["pk"] for item in resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return pks


def get_summary(session: Any) -> dict[str, Any]:
    table  = _table(session)
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "ProjectionExpression": "#s, severity, team",
        "ExpressionAttributeNames": {"#s": "status"},
    }
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    summary: dict[str, Any] = {
        "total": len(items),
        "by_status": {},
        "by_severity": {},
        "by_team": {},
    }
    for item in items:
        s   = item.get("status", "UNKNOWN")
        sev = item.get("severity", "UNKNOWN")
        tm  = item.get("team", "untagged")

        summary["by_status"][s]     = summary["by_status"].get(s, 0) + 1
        summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
        summary["by_team"].setdefault(tm, {"OPEN": 0, "ACKNOWLEDGED": 0, "RESOLVED": 0})
        if s in ("OPEN", "ACKNOWLEDGED", "RESOLVED"):
            summary["by_team"][tm][s] += 1

    return summary
