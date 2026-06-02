"""Append-only audit trail for violation lifecycle transitions."""

import os
from datetime import UTC, datetime
from typing import Any

import structlog
from boto3.dynamodb.conditions import Key

log = structlog.get_logger()

TABLE_NAME = os.environ.get("AUDIT_LOG_TABLE", "cloudshield-audit-log")


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _table(session: Any):
    return session.resource("dynamodb").Table(TABLE_NAME)


def log_transition(
    session: Any,
    *,
    violation_id: str,
    action: str,
    actor: str,
    from_status: str,
    to_status: str,
    context: str = "",
) -> None:
    """Append one event to the violation's audit trail. Never raises — audit failures are logged, not surfaced."""
    try:
        _table(session).put_item(Item={
            "violation_id": violation_id,
            "timestamp":    _now(),
            "action":       action,
            "actor":        actor,
            "from_status":  from_status,
            "to_status":    to_status,
            "context":      context,
        })
        log.info("audit_log.event", violation_id=violation_id, action=action, actor=actor)
    except Exception as exc:  # noqa: BLE001
        log.warning("audit_log.write_failed", violation_id=violation_id, error=str(exc))


def get_history(session: Any, violation_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return lifecycle events for a violation, newest first."""
    resp = _table(session).query(
        KeyConditionExpression=Key("violation_id").eq(violation_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])
