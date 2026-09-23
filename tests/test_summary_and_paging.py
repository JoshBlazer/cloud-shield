"""Tests for the maintained /summary aggregate and cursor pagination."""

from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws
from src.store import violations as store

TABLE_NAME   = "cloudshield-violations"
SUMMARY_NAME = "cloudshield-summary"


def _create_violations_table(session):
    session.resource("dynamodb").create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pk",           "AttributeType": "S"},
            {"AttributeName": "violation_id", "AttributeType": "S"},
            {"AttributeName": "active_pk",    "AttributeType": "S"},
            {"AttributeName": "team",         "AttributeType": "S"},
            {"AttributeName": "last_seen",    "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "violation-id-index",
                "KeySchema": [{"AttributeName": "violation_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "active-pk-index",
                "KeySchema": [
                    {"AttributeName": "active_pk", "KeyType": "HASH"},
                    {"AttributeName": "last_seen", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "team-index",
                "KeySchema": [
                    {"AttributeName": "team",      "KeyType": "HASH"},
                    {"AttributeName": "last_seen", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )


@pytest.fixture
def session(aws_credentials, monkeypatch):
    monkeypatch.setenv("VIOLATIONS_TABLE", TABLE_NAME)
    with mock_aws():
        s = boto3.Session(region_name="us-east-1")
        _create_violations_table(s)
        s.resource("dynamodb").create_table(
            TableName=SUMMARY_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        )
        yield s


@pytest.fixture
def session_no_summary_table(aws_credentials, monkeypatch):
    monkeypatch.setenv("VIOLATIONS_TABLE", TABLE_NAME)
    with mock_aws():
        s = boto3.Session(region_name="us-east-1")
        _create_violations_table(s)
        yield s


def _v(i: int, *, team: str = "infra", severity: str = "HIGH", rule: str = "EC2_001"):
    return {
        "rule_id": rule, "rule_name": rule, "severity": severity,
        "resource_type": "AWS::EC2::SecurityGroup", "resource_id": f"sg-{i:04d}",
        "reason": "open", "team": team,
    }


def _raw_summary(session):
    return session.resource("dynamodb").Table(SUMMARY_NAME).get_item(
        Key={"pk": store.SUMMARY_PK}
    ).get("Item")


# ── maintained aggregate ───────────────────────────────────────────────────────

class TestSummaryAggregate:
    def test_counters_track_every_transition(self, session):
        items = [store.upsert_violation(session, _v(i))[0] for i in range(5)]
        store.upsert_violation(session, _v(99, team="data", severity="CRITICAL"))

        store.acknowledge(session, items[0]["violation_id"])
        store.snooze(session, items[1]["violation_id"], days=3)
        store.exempt(session, items[2]["violation_id"], reason="accepted risk")
        store.mark_resolved(session, items[3]["pk"])

        summary = store.get_summary(session)
        assert summary == store._counters_to_summary(store._scan_counters(session))
        assert summary["total"] == 6
        assert summary["by_status"] == {
            "OPEN": 2, "ACKNOWLEDGED": 1, "SNOOZED": 1, "EXEMPTED": 1, "RESOLVED": 1,
        }
        assert summary["by_severity"] == {"HIGH": 5, "CRITICAL": 1}
        assert summary["by_team"]["infra"] == {"OPEN": 1, "ACKNOWLEDGED": 1, "RESOLVED": 1}
        assert summary["by_team"]["data"] == {"OPEN": 1, "ACKNOWLEDGED": 0, "RESOLVED": 0}

    def test_redetection_does_not_double_count(self, session):
        store.upsert_violation(session, _v(1))
        store.upsert_violation(session, _v(1))
        assert store.get_summary(session)["total"] == 1

    def test_regression_moves_resolved_back_to_open(self, session):
        item, _ = store.upsert_violation(session, _v(1))
        store.mark_resolved(session, item["pk"])
        store.upsert_violation(session, _v(1))
        summary = store.get_summary(session)
        assert summary["total"] == 1
        assert summary["by_status"] == {"OPEN": 1}

    def test_wake_moves_snoozed_back_to_open(self, session):
        item, _ = store.upsert_violation(session, _v(1))
        store.snooze(session, item["violation_id"], days=-1)  # already expired
        assert store.wake_snoozed_violations(session) == 1
        assert store.get_summary(session)["by_status"] == {"OPEN": 1}

    def test_resolve_records_real_from_status(self, session):
        item, _ = store.upsert_violation(session, _v(1))
        store.acknowledge(session, item["violation_id"])
        store.mark_resolved(session, item["pk"])
        summary = store.get_summary(session)
        assert summary["by_status"] == {"RESOLVED": 1}  # ACK -1, not a phantom OPEN -1

    def test_get_summary_reads_aggregate_not_table(self, session):
        store.upsert_violation(session, _v(1))
        # Delete the violation behind the aggregate's back: a scan would say 0
        session.resource("dynamodb").Table(TABLE_NAME).delete_item(Key={"pk": "EC2_001#sg-0001"})
        assert store.get_summary(session)["total"] == 1

    def test_missing_aggregate_is_built_on_first_read(self, session):
        store.upsert_violation(session, _v(1))
        session.resource("dynamodb").Table(SUMMARY_NAME).delete_item(Key={"pk": store.SUMMARY_PK})
        assert store.get_summary(session)["total"] == 1
        assert _raw_summary(session)["rebuilt_at"]

    def test_reconcile_fixes_drift_when_stale(self, session):
        store.upsert_violation(session, _v(1))
        store.rebuild_summary(session)
        # Simulate TTL deleting the item, and an old snapshot
        session.resource("dynamodb").Table(TABLE_NAME).delete_item(Key={"pk": "EC2_001#sg-0001"})
        stale = (datetime.now(tz=UTC) - timedelta(hours=store.SUMMARY_REBUILD_HOURS + 1)).isoformat()
        session.resource("dynamodb").Table(SUMMARY_NAME).update_item(
            Key={"pk": store.SUMMARY_PK},
            UpdateExpression="SET rebuilt_at = :t",
            ExpressionAttributeValues={":t": stale},
        )
        assert store.reconcile_summary_if_stale(session) is True
        assert store.get_summary(session)["total"] == 0

    def test_reconcile_skips_fresh_snapshot(self, session):
        store.upsert_violation(session, _v(1))
        store.rebuild_summary(session)
        assert store.reconcile_summary_if_stale(session) is False

    def test_negative_drift_clamps_to_zero(self):
        summary = store._counters_to_summary({"total": -2, "status#OPEN": -1, "sev#HIGH": 0})
        assert summary == {"total": 0, "by_status": {}, "by_severity": {}, "by_team": {}}

    def test_missing_summary_table_falls_back_to_scan(self, session_no_summary_table):
        s = session_no_summary_table
        item, _ = store.upsert_violation(s, _v(1))  # counter bump fails silently
        store.acknowledge(s, item["violation_id"])
        summary = store.get_summary(s)
        assert summary["total"] == 1
        assert summary["by_status"] == {"ACKNOWLEDGED": 1}


# ── cursor pagination ─────────────────────────────────────────────────────────

def _walk(session, page_size, **filters):
    seen, cursor, pages = [], None, 0
    while True:
        items, cursor = store.list_violations_page(
            session, limit=page_size, cursor=cursor, **filters
        )
        assert len(items) <= page_size
        seen.extend(i["pk"] for i in items)
        pages += 1
        assert pages < 100, "pagination did not terminate"
        if cursor is None:
            return seen, pages


class TestPagination:
    @pytest.mark.parametrize("filters", [
        {},                                  # full scan
        {"status": "OPEN"},                  # sharded active index
        {"team": "infra"},                   # team index
        {"status": "OPEN", "severity": "HIGH"},
    ])
    def test_walk_returns_every_item_exactly_once(self, session, filters):
        for i in range(23):
            store.upsert_violation(session, _v(i))
        seen, pages = _walk(session, 5, **filters)
        assert len(seen) == 23
        assert len(set(seen)) == 23
        assert pages >= 5

    def test_filters_hold_across_pages(self, session):
        for i in range(12):
            store.upsert_violation(session, _v(i, severity="HIGH" if i % 2 else "LOW"))
        for i in range(12, 20):
            store.upsert_violation(session, _v(i, team="data", severity="HIGH"))
        seen, _ = _walk(session, 3, team="infra", severity="HIGH")
        assert sorted(seen) == sorted(f"EC2_001#sg-{i:04d}" for i in range(12) if i % 2)

    def test_resolved_status_pages_via_scan(self, session):
        items = [store.upsert_violation(session, _v(i))[0] for i in range(8)]
        for it in items[:6]:
            store.mark_resolved(session, it["pk"])
        seen, _ = _walk(session, 4, status="RESOLVED")
        assert sorted(seen) == sorted(it["pk"] for it in items[:6])

    def test_single_page_has_no_cursor(self, session):
        for i in range(3):
            store.upsert_violation(session, _v(i))
        items, cursor = store.list_violations_page(session, limit=50)
        assert len(items) == 3
        assert cursor is None

    def test_empty_status_has_no_cursor(self, session):
        items, cursor = store.list_violations_page(session, status="SNOOZED", limit=10)
        assert items == [] and cursor is None

    @pytest.mark.parametrize("bad", ["!!!", "bm90LWpzb24", "WzEsMl0", "eyJzIjo5OTl9"])
    def test_invalid_cursor_raises(self, session, bad):
        # garbage / not JSON / JSON list / out-of-range shard {"s":999}
        with pytest.raises(store.InvalidCursorError):
            store.list_violations_page(session, status="OPEN", cursor=bad)

    def test_list_violations_wrapper_unchanged(self, session):
        for i in range(7):
            store.upsert_violation(session, _v(i))
        assert len(store.list_violations(session, limit=5)) == 5
        assert len(store.list_violations(session, status="OPEN", limit=500)) == 7
