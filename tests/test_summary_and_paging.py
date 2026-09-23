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
        assert summary == {
            "total": 0, "by_status": {}, "by_severity": {}, "by_team": {}, "by_severity_status": {},
        }

    def test_missing_summary_table_falls_back_to_scan(self, session_no_summary_table):
        s = session_no_summary_table
        item, _ = store.upsert_violation(s, _v(1))  # counter bump fails silently
        store.acknowledge(s, item["violation_id"])
        summary = store.get_summary(s)
        assert summary["total"] == 1
        assert summary["by_status"] == {"ACKNOWLEDGED": 1}


# ── severity x status matrix ──────────────────────────────────────────────────

def _matches_rebuild(session):
    summary = store.get_summary(session)
    assert summary == store._counters_to_summary(store._scan_counters(session))
    return summary


class TestSeverityStatusCounters:
    def test_creation(self, session):
        store.upsert_violation(session, _v(1, severity="CRITICAL"))
        store.upsert_violation(session, _v(2, severity="HIGH"))
        store.upsert_violation(session, _v(3, severity="HIGH"))
        summary = _matches_rebuild(session)
        assert summary["by_severity_status"] == {"CRITICAL": {"OPEN": 1}, "HIGH": {"OPEN": 2}}

    @pytest.mark.parametrize(("op", "status"), [
        (lambda s, it: store.acknowledge(s, it["violation_id"]),    "ACKNOWLEDGED"),
        (lambda s, it: store.snooze(s, it["violation_id"], days=3), "SNOOZED"),
        (lambda s, it: store.exempt(s, it["violation_id"], "ok"),   "EXEMPTED"),
        (lambda s, it: store.mark_resolved(s, it["pk"]),            "RESOLVED"),
    ])
    def test_each_transition(self, session, op, status):
        item, _ = store.upsert_violation(session, _v(1, severity="CRITICAL"))
        store.upsert_violation(session, _v(2, severity="CRITICAL"))
        op(session, item)
        summary = _matches_rebuild(session)
        assert summary["by_severity_status"] == {"CRITICAL": {"OPEN": 1, status: 1}}

    def test_wake(self, session):
        item, _ = store.upsert_violation(session, _v(1, severity="MEDIUM"))
        store.snooze(session, item["violation_id"], days=-1)
        assert store.wake_snoozed_violations(session) == 1
        assert _matches_rebuild(session)["by_severity_status"] == {"MEDIUM": {"OPEN": 1}}

    def test_regression(self, session):
        item, _ = store.upsert_violation(session, _v(1, severity="LOW"))
        store.mark_resolved(session, item["pk"])
        store.upsert_violation(session, _v(1, severity="LOW"))
        assert _matches_rebuild(session)["by_severity_status"] == {"LOW": {"OPEN": 1}}

    def test_resolve_from_acknowledged(self, session):
        item, _ = store.upsert_violation(session, _v(1, severity="HIGH"))
        store.acknowledge(session, item["violation_id"])
        store.mark_resolved(session, item["pk"])
        assert _matches_rebuild(session)["by_severity_status"] == {"HIGH": {"RESOLVED": 1}}

    def test_full_lifecycle_matches_rebuild(self, session):
        items = [
            store.upsert_violation(session, _v(i, severity=sev))[0]
            for i, sev in enumerate(["CRITICAL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "HIGH"])
        ]
        store.acknowledge(session, items[0]["violation_id"])
        store.snooze(session, items[1]["violation_id"], days=-1)
        store.exempt(session, items[2]["violation_id"], reason="accepted")
        store.mark_resolved(session, items[3]["pk"])
        store.wake_snoozed_violations(session)
        store.reopen(session, items[2]["violation_id"])
        store.upsert_violation(session, _v(3, severity="MEDIUM"))  # regression
        summary = _matches_rebuild(session)
        assert summary["by_severity_status"] == {
            "CRITICAL": {"ACKNOWLEDGED": 1, "OPEN": 1},
            "HIGH": {"OPEN": 2}, "MEDIUM": {"OPEN": 1}, "LOW": {"OPEN": 1},
        }

    def test_negative_and_zero_counts_omitted(self):
        summary = store._counters_to_summary({
            "sevstatus#HIGH#OPEN": 2, "sevstatus#HIGH#RESOLVED": -1, "sevstatus#LOW#OPEN": 0,
        })
        assert summary["by_severity_status"] == {"HIGH": {"OPEN": 2}}

    def test_old_schema_aggregate_is_rebuilt(self, session):
        store.upsert_violation(session, _v(1))
        store.rebuild_summary(session)
        session.resource("dynamodb").Table(SUMMARY_NAME).update_item(
            Key={"pk": store.SUMMARY_PK}, UpdateExpression="REMOVE #sc",
            ExpressionAttributeNames={"#sc": "schema"},
        )
        assert store.reconcile_summary_if_stale(session) is True
        assert _raw_summary(session)["schema"] == store.SUMMARY_SCHEMA


# ── reopen ────────────────────────────────────────────────────────────────────

class TestReopen:
    @pytest.mark.parametrize("move", [
        lambda s, vid: store.acknowledge(s, vid, by="alice"),
        lambda s, vid: store.snooze(s, vid, days=5),
        lambda s, vid: store.exempt(s, vid, reason="accepted"),
    ])
    def test_reopens_triaged_finding(self, session, move):
        item, _ = store.upsert_violation(session, _v(1, severity="HIGH"))
        move(session, item["violation_id"])
        assert store.reopen(session, item["violation_id"]) is True
        got = store.get_by_id(session, item["violation_id"])
        assert got["status"] == "OPEN"
        assert got["active_pk"] == store._active_pk("OPEN", item["pk"])
        for attr in ("acknowledged_by", "acknowledged_at", "snooze_until", "exempt_reason"):
            assert got[attr] is None
        summary = _matches_rebuild(session)
        assert summary["by_status"] == {"OPEN": 1}
        assert summary["by_severity_status"] == {"HIGH": {"OPEN": 1}}
        assert store.get_active_pks(session) == {item["pk"]}

    def test_refuses_open(self, session):
        item, _ = store.upsert_violation(session, _v(1))
        assert store.reopen(session, item["violation_id"]) is False
        assert _matches_rebuild(session)["by_status"] == {"OPEN": 1}

    def test_refuses_resolved(self, session):
        item, _ = store.upsert_violation(session, _v(1))
        store.mark_resolved(session, item["pk"])
        assert store.reopen(session, item["violation_id"]) is False
        assert store.get_by_id(session, item["violation_id"])["status"] == "RESOLVED"
        assert _matches_rebuild(session)["by_status"] == {"RESOLVED": 1}

    def test_missing_finding(self, session):
        assert store.reopen(session, "no-such-id") is False


# ── trend snapshots ───────────────────────────────────────────────────────────

def _day(offset: int) -> str:
    return (datetime.now(tz=UTC).date() - timedelta(days=offset)).isoformat()


def _put_snapshot(session, offset: int, critical: int):
    session.resource("dynamodb").Table(SUMMARY_NAME).put_item(Item={
        "pk": f"trend#{_day(offset)}", "CRITICAL": critical, "HIGH": 0, "MEDIUM": 0, "LOW": 0,
        "total_active": critical, "recorded_at": "x",
    })


class TestTrend:
    def test_snapshot_counts_active_by_severity(self, session):
        items = [
            store.upsert_violation(session, _v(i, severity=sev))[0]
            for i, sev in enumerate(["CRITICAL", "CRITICAL", "HIGH", "HIGH", "MEDIUM", "LOW"])
        ]
        store.acknowledge(session, items[0]["violation_id"])  # still active
        store.snooze(session, items[2]["violation_id"])       # still active
        store.exempt(session, items[3]["violation_id"])       # not active
        store.mark_resolved(session, items[4]["pk"])          # not active
        snap = store.record_trend_snapshot(session)
        assert snap is not None
        raw = session.resource("dynamodb").Table(SUMMARY_NAME).get_item(
            Key={"pk": f"trend#{_day(0)}"}
        )["Item"]
        assert {k: int(raw[k]) for k in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "total_active")} == {
            "CRITICAL": 2, "HIGH": 1, "MEDIUM": 0, "LOW": 1, "total_active": 4,
        }
        assert raw["recorded_at"]

    def test_last_run_of_day_wins(self, session):
        item, _ = store.upsert_violation(session, _v(1, severity="HIGH"))
        store.record_trend_snapshot(session)
        store.mark_resolved(session, item["pk"])
        store.record_trend_snapshot(session)
        assert store.get_trend(session, 1) == [
            {"date": _day(0), "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "total_active": 0},
        ]

    def test_snapshot_does_not_count_as_summary(self, session):
        store.upsert_violation(session, _v(1))
        store.record_trend_snapshot(session)
        assert store.get_summary(session)["total"] == 1

    def test_snapshot_failure_is_silent(self, session_no_summary_table):
        assert store.record_trend_snapshot(session_no_summary_table) is None

    def test_get_trend_oldest_first_and_omits_missing(self, session):
        for offset, n in ((0, 5), (2, 3), (5, 1)):
            _put_snapshot(session, offset, n)
        trend = store.get_trend(session, 14)
        assert [d["date"] for d in trend] == [_day(5), _day(2), _day(0)]
        assert [d["CRITICAL"] for d in trend] == [1, 3, 5]
        assert set(trend[0]) == {"date", "CRITICAL", "HIGH", "MEDIUM", "LOW", "total_active"}
        assert all(isinstance(v, int) for d in trend for k, v in d.items() if k != "date")

    def test_get_trend_respects_window(self, session):
        for offset in (0, 2, 3, 95):
            _put_snapshot(session, offset, offset)
        assert [d["date"] for d in store.get_trend(session, 3)] == [_day(2), _day(0)]
        assert [d["date"] for d in store.get_trend(session, 1)] == [_day(0)]
        assert len(store.get_trend(session, 500)) == 3  # capped at 90 days

    def test_get_trend_without_table_is_empty(self, session_no_summary_table):
        assert store.get_trend(session_no_summary_table, 7) == []


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
