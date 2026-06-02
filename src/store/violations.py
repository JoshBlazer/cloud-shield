"""DynamoDB violation store — CRUD and full lifecycle management."""

import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from src.store import audit_log

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
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{rule_id}#{resource_id}"))


# ── Write operations ──────────────────────────────────────────────────────────

def upsert_violation(
    session: Any,
    violation: dict[str, Any],
    tags: dict[str, str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """
    Atomic violation upsert. Three phases:

    1. Conditional create (attribute_not_exists) — atomic, only one concurrent caller wins.
    2. Conditional update — fires if item is ACTIVE or EXEMPTED; bumps last_seen silently.
       EXEMPTED items are re-detected every run but never re-alert (is_new stays False).
    3. Unconditional overwrite — reached only when item is RESOLVED (regression).
       Returns is_new=True so the caller re-alerts.

    active_pk mirrors status for ACTIVE items and is absent for RESOLVED/EXEMPTED.
    This makes active-pk-index a sparse index — RESOLVED items are off the index entirely,
    preventing the hot-partition problem of all OPEN items sharing one GSI partition.
    """
    table      = _table(session)
    rule_id    = violation["rule_id"]
    resource_id = violation["resource_id"]
    pk         = _pk(rule_id, resource_id)
    now        = _now()

    new_item: dict[str, Any] = {
        "pk":               pk,
        "violation_id":     _stable_id(rule_id, resource_id),
        "rule_id":          rule_id,
        "rule_name":        violation["rule_name"],
        "severity":         violation["severity"],
        "resource_type":    violation["resource_type"],
        "resource_id":      resource_id,
        "reason":           violation["reason"],
        "status":           STATUS_OPEN,
        "active_pk":        STATUS_OPEN,  # sparse index key — present only on active items
        "first_detected":   now,
        "last_seen":        now,
        "occurrence_count": 1,
        "resolved_at":      None,
        "acknowledged_by":  None,
        "acknowledged_at":  None,
        "snooze_until":     None,
        "exempt_reason":    None,
        "team":  violation.get("team") or (tags or {}).get("team", "untagged"),
        "owner": violation.get("owner") or (tags or {}).get("owner"),
        "region":     violation.get("region") or os.environ.get("AWS_REGION", "us-east-1"),
        "account_id": violation.get("account_id") or os.environ.get("AWS_ACCOUNT_ID", "unknown"),
    }

    # Phase 1: atomic create
    try:
        table.put_item(Item=new_item, ConditionExpression=Attr("pk").not_exists())
        log.info("store.created", pk=pk)
        return new_item, True
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

    # Phase 2: exists and is active or exempted — bump silently
    try:
        result = table.update_item(
            Key={"pk": pk},
            UpdateExpression="SET last_seen = :ls, occurrence_count = occurrence_count + :one",
            ConditionExpression=Attr("status").is_in(list(ACTIVE_STATUSES | {STATUS_EXEMPTED})),
            ExpressionAttributeValues={":ls": now, ":one": 1},
            ReturnValues="ALL_NEW",
        )
        return result["Attributes"], False
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

    # Phase 3: was RESOLVED — regression, create fresh OPEN item
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
        UpdateExpression="SET #s=:acked, acknowledged_by=:by, acknowledged_at=:at, active_pk=:acked",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":acked": STATUS_ACKNOWLEDGED, ":by": by, ":at": now},
    )
    audit_log.log_transition(
        session,
        violation_id=violation_id,
        action="acknowledge",
        actor=by,
        from_status=item.get("status", STATUS_OPEN),
        to_status=STATUS_ACKNOWLEDGED,
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
        UpdateExpression="SET #s=:snoozed, snooze_until=:u, active_pk=:snoozed",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":snoozed": STATUS_SNOOZED, ":u": until},
    )
    audit_log.log_transition(
        session,
        violation_id=violation_id,
        action="snooze",
        actor="dashboard-user",
        from_status=item.get("status", STATUS_OPEN),
        to_status=STATUS_SNOOZED,
        context=f"{days}d",
    )
    log.info("store.snoozed", violation_id=violation_id, days=days)
    return True


def exempt(session: Any, violation_id: str, reason: str = "") -> bool:
    item = get_by_id(session, violation_id)
    if not item:
        return False
    _table(session).update_item(
        Key={"pk": item["pk"]},
        UpdateExpression="SET #s=:ex, exempt_reason=:r REMOVE active_pk",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":ex": STATUS_EXEMPTED, ":r": reason},
    )
    audit_log.log_transition(
        session,
        violation_id=violation_id,
        action="exempt",
        actor="dashboard-user",
        from_status=item.get("status", STATUS_OPEN),
        to_status=STATUS_EXEMPTED,
        context=reason,
    )
    log.info("store.exempted", violation_id=violation_id)
    return True


def mark_resolved(session: Any, pk: str) -> None:
    ttl = int(time.time()) + 90 * 86_400  # expire 90 days after resolution
    try:
        result = _table(session).update_item(
            Key={"pk": pk},
            UpdateExpression="SET #s=:s, resolved_at=:r, #ttl=:ttl REMOVE active_pk",
            ExpressionAttributeNames={"#s": "status", "#ttl": "ttl"},
            ExpressionAttributeValues={":s": STATUS_RESOLVED, ":r": _now(), ":ttl": ttl},
            ConditionExpression=Attr("status").is_in(list(ACTIVE_STATUSES)),
            ReturnValues="ALL_NEW",
        )
        vid = result["Attributes"].get("violation_id", "")
        if vid:
            audit_log.log_transition(
                session,
                violation_id=vid,
                action="resolve",
                actor="auditor",
                from_status=STATUS_OPEN,
                to_status=STATUS_RESOLVED,
            )
        log.info("store.resolved", pk=pk)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def wake_snoozed_violations(session: Any) -> int:
    """Re-open any SNOOZED violations whose snooze_until has passed."""
    table = _table(session)
    now   = _now()
    woken = 0

    kwargs: dict[str, Any] = {
        "IndexName": "active-pk-index",
        "KeyConditionExpression": Key("active_pk").eq(STATUS_SNOOZED),
        "FilterExpression": Attr("snooze_until").lt(now),
        "ProjectionExpression": "pk, violation_id",
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            try:
                table.update_item(
                    Key={"pk": item["pk"]},
                    UpdateExpression="SET #s = :open, active_pk = :open, snooze_until = :null",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":open": STATUS_OPEN, ":null": None},
                    ConditionExpression=Attr("status").eq(STATUS_SNOOZED),
                )
                woken += 1
                if item.get("violation_id"):
                    audit_log.log_transition(
                        session,
                        violation_id=item["violation_id"],
                        action="wake",
                        actor="auditor",
                        from_status=STATUS_SNOOZED,
                        to_status=STATUS_OPEN,
                    )
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
        kwargs: dict[str, Any] = {
            "IndexName": "team-index",
            "KeyConditionExpression": Key("team").eq(team),
            "Limit": limit,
        }
        if status:
            kwargs["FilterExpression"] = Attr("status").eq(status)
        resp = table.query(**kwargs)
        items = resp.get("Items", [])

    elif status in ACTIVE_STATUSES:
        # active-pk-index: sparse — RESOLVED/EXEMPTED items are not here
        kwargs = {
            "IndexName": "active-pk-index",
            "KeyConditionExpression": Key("active_pk").eq(status),
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

    elif status:
        # RESOLVED / EXEMPTED: off the sparse index, scan with filter
        kwargs = {"FilterExpression": Attr("status").eq(status)}
        if severity:
            kwargs["FilterExpression"] = kwargs["FilterExpression"] & Attr("severity").eq(severity)
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp or len(items) >= limit:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        items = items[:limit]

    else:
        # No filter — full scan
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
    """Return all PKs in an active status, paginated. Uses sparse active-pk-index."""
    pks: set[str] = set()
    table = _table(session)
    for s in ACTIVE_STATUSES:
        kwargs: dict[str, Any] = {
            "IndexName": "active-pk-index",
            "KeyConditionExpression": Key("active_pk").eq(s),
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
