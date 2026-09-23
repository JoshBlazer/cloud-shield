"""DynamoDB violation store — CRUD and full lifecycle management."""

import base64
import binascii
import json
import os
import time
import uuid
import zlib
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

ACTIVE_STATUSES     = {STATUS_OPEN, STATUS_ACKNOWLEDGED, STATUS_SNOOZED}
REOPENABLE_STATUSES = {STATUS_ACKNOWLEDGED, STATUS_SNOOZED, STATUS_EXEMPTED}

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

# active-pk-index write sharding. The GSI hash key is f"{status}#{shard}" so a
# single dominant status (e.g. OPEN) is spread across SHARD_COUNT partitions
# instead of hammering one. Queries fan out over all shards and merge.
# Fixed at deploy time — changing it requires re-sharding existing items, since
# the shard is derived from the (stable) pk and only rewritten on status change.
SHARD_COUNT = max(1, int(os.environ.get("ACTIVE_PK_SHARDS", "10")))

# Maintained summary aggregate. One item holds flat counters ("total",
# "status#OPEN", "sev#HIGH", "team#infra#OPEN") that every lifecycle transition
# bumps with an atomic ADD, so GET /summary is a single GetItem instead of a
# table scan. Counters can drift (TTL deletes of resolved items, a delta lost
# to a concurrent rebuild), so the auditor reconciles with a full rebuild once
# the snapshot is older than SUMMARY_REBUILD_HOURS.
SUMMARY_TABLE         = os.environ.get("SUMMARY_TABLE", "cloudshield-summary")
SUMMARY_PK            = "global"
SUMMARY_REBUILD_HOURS = float(os.environ.get("SUMMARY_REBUILD_HOURS", "24"))
# Bumped whenever a counter family is added: an aggregate built by an older
# schema lacks the new family, so reconcile rebuilds it regardless of age.
SUMMARY_SCHEMA        = 2
# Non-counter attributes on the aggregate item.
_SUMMARY_META         = ("pk", "rebuilt_at", "schema")

# Daily trend snapshots share the summary table, one item per UTC date.
TREND_PK_PREFIX = "trend#"
TREND_MAX_DAYS  = 90


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _table(session: Any) -> Any:
    return session.resource("dynamodb").Table(TABLE_NAME)


def _pk(rule_id: str, resource_id: str) -> str:
    return f"{rule_id}#{resource_id}"


def _stable_id(rule_id: str, resource_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{rule_id}#{resource_id}"))


def _shard(pk: str) -> int:
    """Deterministic shard for a pk — same violation always lands on the same shard."""
    return zlib.crc32(pk.encode()) % SHARD_COUNT


def _active_pk(status: str, pk: str) -> str:
    """High-cardinality GSI hash key: spreads a status across SHARD_COUNT partitions."""
    return f"{status}#{_shard(pk)}"


def _active_pk_shards(status: str) -> list[str]:
    """All shard keys for a status — used to fan out queries."""
    return [f"{status}#{i}" for i in range(SHARD_COUNT)]


# ── Summary counters ──────────────────────────────────────────────────────────

def _summary_table(session: Any) -> Any:
    return session.resource("dynamodb").Table(SUMMARY_TABLE)


def _created_deltas(severity: str, team: str) -> dict[str, int]:
    return {
        "total": 1,
        f"sev#{severity}": 1,
        f"status#{STATUS_OPEN}": 1,
        f"team#{team}#{STATUS_OPEN}": 1,
        f"sevstatus#{severity}#{STATUS_OPEN}": 1,
    }


def _transition_deltas(
    team: str, severity: str, from_status: str, to_status: str,
) -> dict[str, int]:
    if from_status == to_status:
        return {}
    return {
        f"status#{from_status}": -1,
        f"status#{to_status}": 1,
        f"team#{team}#{from_status}": -1,
        f"team#{team}#{to_status}": 1,
        f"sevstatus#{severity}#{from_status}": -1,
        f"sevstatus#{severity}#{to_status}": 1,
    }


def _bump_summary(session: Any, deltas: dict[str, int]) -> None:
    """Atomically apply counter deltas. Best-effort: the counters are a derived
    cache, so a failure here must never fail the lifecycle write it describes."""
    if not deltas:
        return
    names  = {f"#a{i}": k for i, k in enumerate(deltas)}
    values = {f":v{i}": v for i, v in enumerate(deltas.values())}
    expr   = "ADD " + ", ".join(f"#a{i} :v{i}" for i in range(len(deltas)))
    try:
        _summary_table(session).update_item(
            Key={"pk": SUMMARY_PK},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except ClientError as exc:
        log.warning("store.summary_bump_failed", error=str(exc))


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

    active_pk is f"{status}#{shard}" for ACTIVE items and absent for RESOLVED/EXEMPTED.
    The index is therefore both sparse (RESOLVED/EXEMPTED items are off it entirely)
    and sharded (each status is spread across SHARD_COUNT partitions), so a dominant
    status like OPEN no longer hammers a single GSI partition.
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
        "active_pk":        _active_pk(STATUS_OPEN, pk),  # sharded sparse-index key
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
        _bump_summary(session, _created_deltas(new_item["severity"], new_item["team"]))
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
    _bump_summary(session, _transition_deltas(
        new_item["team"], new_item["severity"], STATUS_RESOLVED, STATUS_OPEN,
    ))
    log.info("store.regression", pk=pk)
    return new_item, True


def acknowledge(session: Any, violation_id: str, by: str = "user") -> bool:
    item = get_by_id(session, violation_id)
    if not item:
        return False
    now = _now()
    _table(session).update_item(
        Key={"pk": item["pk"]},
        UpdateExpression="SET #s=:acked, acknowledged_by=:by, acknowledged_at=:at, active_pk=:apk",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":acked": STATUS_ACKNOWLEDGED,
            ":by": by,
            ":at": now,
            ":apk": _active_pk(STATUS_ACKNOWLEDGED, item["pk"]),
        },
    )
    _bump_summary(session, _transition_deltas(
        item.get("team", "untagged"), item.get("severity", "UNKNOWN"),
        item.get("status", STATUS_OPEN), STATUS_ACKNOWLEDGED,
    ))
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
        UpdateExpression="SET #s=:snoozed, snooze_until=:u, active_pk=:apk",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":snoozed": STATUS_SNOOZED,
            ":u": until,
            ":apk": _active_pk(STATUS_SNOOZED, item["pk"]),
        },
    )
    _bump_summary(session, _transition_deltas(
        item.get("team", "untagged"), item.get("severity", "UNKNOWN"),
        item.get("status", STATUS_OPEN), STATUS_SNOOZED,
    ))
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
    _bump_summary(session, _transition_deltas(
        item.get("team", "untagged"), item.get("severity", "UNKNOWN"),
        item.get("status", STATUS_OPEN), STATUS_EXEMPTED,
    ))
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


def reopen(session: Any, violation_id: str, by: str = "dashboard-user") -> bool:
    """Move an ACKNOWLEDGED, SNOOZED or EXEMPTED finding back to OPEN. Returns
    False if it doesn't exist or isn't reopenable (OPEN/RESOLVED are untouched)."""
    item = get_by_id(session, violation_id)
    if not item or item.get("status") not in REOPENABLE_STATUSES:
        return False
    from_status = item["status"]
    try:
        # Conditioned on the status we read, so the deltas describe the real transition.
        _table(session).update_item(
            Key={"pk": item["pk"]},
            UpdateExpression=(
                "SET #s=:open, active_pk=:apk, acknowledged_by=:null, acknowledged_at=:null, "
                "snooze_until=:null, exempt_reason=:null"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":open": STATUS_OPEN,
                ":apk":  _active_pk(STATUS_OPEN, item["pk"]),
                ":null": None,
                ":from": from_status,
            },
            ConditionExpression="#s = :from",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False
    _bump_summary(session, _transition_deltas(
        item.get("team", "untagged"), item.get("severity", "UNKNOWN"),
        from_status, STATUS_OPEN,
    ))
    audit_log.log_transition(
        session,
        violation_id=violation_id,
        action="reopen",
        actor=by,
        from_status=from_status,
        to_status=STATUS_OPEN,
    )
    log.info("store.reopened", violation_id=violation_id, by=by)
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
            ReturnValues="ALL_OLD",
        )
        old         = result["Attributes"]
        from_status = old.get("status", STATUS_OPEN)
        _bump_summary(session, _transition_deltas(
            old.get("team", "untagged"), old.get("severity", "UNKNOWN"),
            from_status, STATUS_RESOLVED,
        ))
        vid = old.get("violation_id", "")
        if vid:
            audit_log.log_transition(
                session,
                violation_id=vid,
                action="resolve",
                actor="auditor",
                from_status=from_status,
                to_status=STATUS_RESOLVED,
            )
        log.info("store.resolved", pk=pk)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def wake_snoozed_violations(session: Any) -> int:
    """Re-open any SNOOZED violations whose snooze_until has passed. Fans out over shards."""
    table = _table(session)
    now   = _now()
    woken = 0

    for shard_key in _active_pk_shards(STATUS_SNOOZED):
        kwargs: dict[str, Any] = {
            "IndexName": "active-pk-index",
            "KeyConditionExpression": Key("active_pk").eq(shard_key),
            "FilterExpression": Attr("snooze_until").lt(now),
            "ProjectionExpression": "pk, violation_id, team, severity",
        }
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                try:
                    table.update_item(
                        Key={"pk": item["pk"]},
                        UpdateExpression="SET #s = :open, active_pk = :apk, snooze_until = :null",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={
                            ":open": STATUS_OPEN,
                            ":apk": _active_pk(STATUS_OPEN, item["pk"]),
                            ":null": None,
                        },
                        ConditionExpression=Attr("status").eq(STATUS_SNOOZED),
                    )
                    woken += 1
                    _bump_summary(session, _transition_deltas(
                        item.get("team", "untagged"), item.get("severity", "UNKNOWN"),
                        STATUS_SNOOZED, STATUS_OPEN,
                    ))
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


class InvalidCursorError(ValueError):
    """Raised when a pagination cursor can't be decoded."""


def _encode_cursor(state: dict[str, Any]) -> str:
    raw = json.dumps(state, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        state  = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError("invalid cursor") from exc
    if not isinstance(state, dict):
        raise InvalidCursorError("invalid cursor")
    return state


def _collect(
    op: Any, kwargs: dict[str, Any], want: int, start_key: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """
    Page through a query/scan until `want` items are collected or it's exhausted.

    Each call asks for at most the number still needed, so the returned
    LastEvaluatedKey is an exact resume point: nothing past it has been read
    and silently dropped (which slicing an over-read page would do).
    """
    items: list[dict[str, Any]] = []
    key = start_key
    while len(items) < want:
        call = {**kwargs, "Limit": want - len(items)}
        if key:
            call["ExclusiveStartKey"] = key
        resp = op(**call)
        items.extend(resp.get("Items", []))
        key = resp.get("LastEvaluatedKey")
        if not key:
            return items, None
    return items, key


def list_violations_page(
    session: Any,
    status: str | None = None,
    severity: str | None = None,
    team: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    One page of violations plus an opaque cursor for the next page (None when done).

    A cursor is only meaningful with the same filters it was issued for.
    Raises InvalidCursorError on a malformed cursor.
    """
    table     = _table(session)
    limit     = max(1, limit)
    state     = _decode_cursor(cursor) if cursor else {}
    start_key = state.get("k")

    filt: Any = Attr("severity").eq(severity) if severity else None

    if team:
        kwargs: dict[str, Any] = {
            "IndexName": "team-index",
            "KeyConditionExpression": Key("team").eq(team),
        }
        if status:
            filt = Attr("status").eq(status) if filt is None else filt & Attr("status").eq(status)
        if filt is not None:
            kwargs["FilterExpression"] = filt
        items, lek = _collect(table.query, kwargs, limit, start_key)
        return items, _encode_cursor({"k": lek}) if lek else None

    if status in ACTIVE_STATUSES:
        # active-pk-index: sparse + sharded. Walk the shards in order; the cursor
        # records which shard we stopped in and where within it.
        shards = _active_pk_shards(status)
        shard  = state.get("s", 0)
        if not isinstance(shard, int) or not 0 <= shard < len(shards):
            raise InvalidCursorError("invalid cursor")
        items = []
        while shard < len(shards):
            kwargs = {
                "IndexName": "active-pk-index",
                "KeyConditionExpression": Key("active_pk").eq(shards[shard]),
            }
            if filt is not None:
                kwargs["FilterExpression"] = filt
            got, lek = _collect(table.query, kwargs, limit - len(items), start_key)
            items.extend(got)
            if lek:
                return items, _encode_cursor({"s": shard, "k": lek})
            shard, start_key = shard + 1, None
            if len(items) >= limit:
                return items, _encode_cursor({"s": shard}) if shard < len(shards) else None
        return items, None

    # RESOLVED / EXEMPTED are off the sparse index, and no status means
    # everything: both are a filtered scan.
    kwargs = {}
    if status:
        filt = Attr("status").eq(status) if filt is None else Attr("status").eq(status) & filt
    if filt is not None:
        kwargs["FilterExpression"] = filt
    items, lek = _collect(table.scan, kwargs, limit, start_key)
    return items, _encode_cursor({"k": lek}) if lek else None


def list_violations(
    session: Any,
    status: str | None = None,
    severity: str | None = None,
    team: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """First page of violations (see list_violations_page for cursor paging)."""
    items, _ = list_violations_page(session, status, severity, team, limit)
    return items


def get_active_pks(session: Any) -> set[str]:
    """Return all PKs in an active status. Fans out over sharded active-pk-index, paginated."""
    pks: set[str] = set()
    table = _table(session)
    for s in ACTIVE_STATUSES:
        for shard_key in _active_pk_shards(s):
            kwargs: dict[str, Any] = {
                "IndexName": "active-pk-index",
                "KeyConditionExpression": Key("active_pk").eq(shard_key),
                "ProjectionExpression": "pk",
            }
            while True:
                resp = table.query(**kwargs)
                pks.update(item["pk"] for item in resp.get("Items", []))
                if "LastEvaluatedKey" not in resp:
                    break
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return pks


def _scan_counters(session: Any) -> dict[str, int]:
    """Recompute every summary counter from the violations table (full scan)."""
    counters: dict[str, int] = {"total": 0}
    kwargs: dict[str, Any] = {
        "ProjectionExpression": "#s, severity, team",
        "ExpressionAttributeNames": {"#s": "status"},
    }
    table = _table(session)
    while True:
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            s   = item.get("status", "UNKNOWN")
            sev = item.get("severity", "UNKNOWN")
            tm  = item.get("team", "untagged")
            for key in (
                "total", f"status#{s}", f"sev#{sev}", f"team#{tm}#{s}", f"sevstatus#{sev}#{s}",
            ):
                counters[key] = counters.get(key, 0) + 1
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return counters


def _counters_to_summary(counters: dict[str, Any]) -> dict[str, Any]:
    """Reshape flat counters into the /summary response. Negative drift clamps to 0."""
    summary: dict[str, Any] = {
        "total": max(0, int(counters.get("total", 0))),
        "by_status": {},
        "by_severity": {},
        "by_team": {},
        "by_severity_status": {},
    }
    for key, raw in counters.items():
        n = max(0, int(raw))  # DynamoDB returns Decimal
        if not n:
            continue
        if key.startswith("status#"):
            summary["by_status"][key[len("status#"):]] = n
        elif key.startswith("sev#"):
            summary["by_severity"][key[len("sev#"):]] = n
        elif key.startswith("team#"):
            team, _, status = key[len("team#"):].rpartition("#")
            bucket = summary["by_team"].setdefault(
                team, {"OPEN": 0, "ACKNOWLEDGED": 0, "RESOLVED": 0},
            )
            if status in bucket:
                bucket[status] = n
        elif key.startswith("sevstatus#"):
            sev, _, status = key[len("sevstatus#"):].rpartition("#")
            summary["by_severity_status"].setdefault(sev, {})[status] = n
    return summary


def rebuild_summary(session: Any) -> dict[str, Any]:
    """Reconcile the aggregate from a full scan and store it. Returns the summary."""
    counters = _scan_counters(session)
    try:
        _summary_table(session).put_item(
            Item={"pk": SUMMARY_PK, "rebuilt_at": _now(), "schema": SUMMARY_SCHEMA, **counters},
        )
        log.info("store.summary_rebuilt", total=counters["total"])
    except ClientError as exc:
        log.warning("store.summary_rebuild_failed", error=str(exc))
    return _counters_to_summary(counters)


def reconcile_summary_if_stale(session: Any) -> bool:
    """Rebuild the aggregate if it's missing, from an older SUMMARY_SCHEMA, or
    older than SUMMARY_REBUILD_HOURS."""
    try:
        item = _summary_table(session).get_item(Key={"pk": SUMMARY_PK}).get("Item")
    except ClientError as exc:
        log.warning("store.summary_read_failed", error=str(exc))
        return False
    if item and item.get("rebuilt_at") and int(item.get("schema", 1)) >= SUMMARY_SCHEMA:
        age = datetime.now(tz=UTC) - datetime.fromisoformat(str(item["rebuilt_at"]))
        if age < timedelta(hours=SUMMARY_REBUILD_HOURS):
            return False
    rebuild_summary(session)
    return True


def get_summary(session: Any) -> dict[str, Any]:
    """
    Aggregate counts by status, severity, and team.

    Reads the maintained aggregate (one GetItem). If it doesn't exist yet it is
    built from a scan once; if the summary table is unavailable, falls back to
    scanning without persisting.
    """
    try:
        item = _summary_table(session).get_item(Key={"pk": SUMMARY_PK}).get("Item")
    except ClientError as exc:
        log.warning("store.summary_read_failed", error=str(exc))
        return _counters_to_summary(_scan_counters(session))
    if not item:
        return rebuild_summary(session)
    return _counters_to_summary({k: v for k, v in item.items() if k not in _SUMMARY_META})


# ── Trend snapshots ───────────────────────────────────────────────────────────

def _trend_pk(day: str) -> str:
    return f"{TREND_PK_PREFIX}{day}"


def _active_by_severity(counters: dict[str, Any]) -> dict[str, int]:
    """Active (OPEN + ACKNOWLEDGED + SNOOZED) counts per severity, from sevstatus counters."""
    counts = dict.fromkeys(SEVERITIES, 0)
    total  = 0
    for key, raw in counters.items():
        if not key.startswith("sevstatus#"):
            continue
        sev, _, status = key[len("sevstatus#"):].rpartition("#")
        if status not in ACTIVE_STATUSES:
            continue
        n = max(0, int(raw))  # clamp negative drift, like /summary
        total += n
        if sev in counts:
            counts[sev] += n
    return {**counts, "total_active": total}


def record_trend_snapshot(session: Any) -> dict[str, Any] | None:
    """Store today's (UTC) active-by-severity snapshot, overwriting any earlier
    run today. Best-effort: logs and returns None on failure."""
    table = _summary_table(session)
    try:
        item = table.get_item(Key={"pk": SUMMARY_PK}).get("Item") or {}
        snapshot: dict[str, Any] = {
            "pk":          _trend_pk(datetime.now(tz=UTC).date().isoformat()),
            **_active_by_severity({k: v for k, v in item.items() if k not in _SUMMARY_META}),
            "recorded_at": _now(),
        }
        table.put_item(Item=snapshot)
    except ClientError as exc:
        log.warning("store.trend_snapshot_failed", error=str(exc))
        return None
    log.info("store.trend_snapshot", pk=snapshot["pk"], total_active=snapshot["total_active"])
    return snapshot


def get_trend(session: Any, days: int) -> list[dict[str, Any]]:
    """Snapshots for the last `days` UTC dates (today included), oldest first.
    Dates without a snapshot are omitted."""
    days  = max(1, min(TREND_MAX_DAYS, days))
    today = datetime.now(tz=UTC).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    found: dict[str, dict[str, Any]] = {}
    ddb   = session.resource("dynamodb")
    try:
        for i in range(0, len(dates), 100):  # BatchGetItem takes at most 100 keys
            pending: dict[str, Any] = {
                SUMMARY_TABLE: {"Keys": [{"pk": _trend_pk(d)} for d in dates[i:i + 100]]},
            }
            while pending:
                resp = ddb.batch_get_item(RequestItems=pending)
                for item in resp.get("Responses", {}).get(SUMMARY_TABLE, []):
                    found[str(item["pk"])[len(TREND_PK_PREFIX):]] = item
                pending = resp.get("UnprocessedKeys") or {}
    except ClientError as exc:
        log.warning("store.trend_read_failed", error=str(exc))
        return []
    return [
        {
            "date": d,
            **{sev: int(found[d].get(sev, 0)) for sev in SEVERITIES},
            "total_active": int(found[d].get("total_active", 0)),
        }
        for d in dates if d in found
    ]
