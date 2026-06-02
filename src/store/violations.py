"""DynamoDB violation store — CRUD and full lifecycle management."""

import os
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
    Idempotent write: update last_seen on an active violation or create a new one.

    Returns (item, is_new). is_new=True means the violation was just created —
    the caller should send an alert. is_new=False means it was already tracked.
    """
    table = _table(session)
    rule_id    = violation["rule_id"]
    resource_id = violation["resource_id"]
    pk         = _pk(rule_id, resource_id)
    now        = _now()

    existing = table.get_item(Key={"pk": pk}).get("Item")

    if existing and existing["status"] in ACTIVE_STATUSES:
        table.update_item(
            Key={"pk": pk},
            UpdateExpression=(
                "SET last_seen = :ls, "
                "occurrence_count = occurrence_count + :one"
            ),
            ExpressionAttributeValues={":ls": now, ":one": 1},
        )
        existing["last_seen"] = now
        existing["occurrence_count"] = int(existing.get("occurrence_count", 1)) + 1
        return existing, False

    item: dict[str, Any] = {
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
        "region":         os.environ.get("AWS_REGION", "us-east-1"),
        "account_id":     os.environ.get("AWS_ACCOUNT_ID", "unknown"),
    }
    table.put_item(Item=item)
    log.info("store.created", pk=pk)
    return item, True


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
    try:
        _table(session).update_item(
            Key={"pk": pk},
            UpdateExpression="SET #s=:s, resolved_at=:r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": STATUS_RESOLVED, ":r": _now()},
            ConditionExpression=Attr("status").is_in(list(ACTIVE_STATUSES)),
        )
        log.info("store.resolved", pk=pk)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


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

    if team:
        resp = table.query(
            IndexName="team-index",
            KeyConditionExpression=Key("team").eq(team),
            FilterExpression=(Attr("status").eq(status) if status else Attr("pk").exists()),
            Limit=limit,
        )
    elif status:
        kwargs: dict[str, Any] = {
            "IndexName": "status-index",
            "KeyConditionExpression": Key("status").eq(status),
            "Limit": limit,
        }
        if severity:
            kwargs["FilterExpression"] = Attr("severity").eq(severity)
        resp = table.query(**kwargs)
    else:
        kwargs = {"Limit": limit}
        if severity:
            kwargs["FilterExpression"] = Attr("severity").eq(severity)
        resp = table.scan(**kwargs)

    return resp.get("Items", [])


def get_active_pks(session: Any) -> set[str]:
    """Return all PKs currently in an active (non-resolved) status."""
    pks: set[str] = set()
    for s in ACTIVE_STATUSES:
        resp = _table(session).query(
            IndexName="status-index",
            KeyConditionExpression=Key("status").eq(s),
            ProjectionExpression="pk",
        )
        pks.update(item["pk"] for item in resp.get("Items", []))
    return pks


def get_summary(session: Any) -> dict[str, Any]:
    table  = _table(session)
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "ProjectionExpression": "#s, severity, team",
        "ExpressionAttributeNames": {"#s": "status"},
    }
    # Paginate — scan returns at most 1 MB per call
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

        summary["by_status"][s]   = summary["by_status"].get(s, 0) + 1
        summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
        summary["by_team"].setdefault(tm, {"OPEN": 0, "ACKNOWLEDGED": 0, "RESOLVED": 0})
        if s in ("OPEN", "ACKNOWLEDGED", "RESOLVED"):
            summary["by_team"][tm][s] += 1

    return summary
