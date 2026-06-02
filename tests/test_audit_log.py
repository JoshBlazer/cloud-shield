"""Tests for the violation audit trail and its integration with lifecycle ops."""

import boto3
import pytest
from moto import mock_aws
from src.store import audit_log
from src.store import violations as store

VIOL_TABLE = "cloudshield-violations"
AUDIT_TABLE = "cloudshield-audit-log"


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID",     "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN",    "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN",     "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION",    "us-east-1")
    monkeypatch.setenv("VIOLATIONS_TABLE",      VIOL_TABLE)
    monkeypatch.setenv("AUDIT_LOG_TABLE",       AUDIT_TABLE)


@pytest.fixture
def session(aws_credentials):
    with mock_aws():
        sess = boto3.Session(region_name="us-east-1")
        ddb  = sess.resource("dynamodb")

        ddb.create_table(
            TableName=VIOL_TABLE,
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

        ddb.create_table(
            TableName=AUDIT_TABLE,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "violation_id", "AttributeType": "S"},
                {"AttributeName": "timestamp",    "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "violation_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp",    "KeyType": "RANGE"},
            ],
        )
        yield sess


@pytest.fixture
def sample():
    return {
        "rule_id": "S3_001", "rule_name": "No Public S3 Buckets", "severity": "CRITICAL",
        "resource_type": "AWS::S3::Bucket", "resource_id": "my-bucket",
        "reason": "public", "team": "data-platform",
    }


class TestAuditLogDirect:
    def test_log_and_read_back(self, session):
        audit_log.log_transition(
            session, violation_id="v-1", action="acknowledge", actor="alice",
            from_status="OPEN", to_status="ACKNOWLEDGED",
        )
        events = audit_log.get_history(session, "v-1")
        assert len(events) == 1
        assert events[0]["action"] == "acknowledge"
        assert events[0]["actor"] == "alice"

    def test_history_newest_first(self, session):
        for action in ("detect", "acknowledge", "resolve"):
            audit_log.log_transition(
                session, violation_id="v-2", action=action, actor="x",
                from_status="OPEN", to_status="OPEN",
            )
        events = audit_log.get_history(session, "v-2")
        assert [e["action"] for e in events] == ["resolve", "acknowledge", "detect"]

    def test_write_failure_is_silent(self, aws_credentials):
        # No table created — write must not raise
        with mock_aws():
            sess = boto3.Session(region_name="us-east-1")
            audit_log.log_transition(
                sess, violation_id="v-3", action="snooze", actor="y",
                from_status="OPEN", to_status="SNOOZED",
            )  # should not raise


class TestLifecycleWritesAudit:
    def test_acknowledge_records_event(self, session, sample):
        item, _ = store.upsert_violation(session, sample)
        store.acknowledge(session, item["violation_id"], by="reviewer@acme.com")
        events = audit_log.get_history(session, item["violation_id"])
        ack = [e for e in events if e["action"] == "acknowledge"]
        assert len(ack) == 1
        assert ack[0]["actor"] == "reviewer@acme.com"
        assert ack[0]["to_status"] == "ACKNOWLEDGED"

    def test_exempt_records_reason(self, session, sample):
        item, _ = store.upsert_violation(session, sample)
        store.exempt(session, item["violation_id"], reason="legacy, migration Q3")
        events = audit_log.get_history(session, item["violation_id"])
        ex = [e for e in events if e["action"] == "exempt"]
        assert len(ex) == 1
        assert ex[0]["context"] == "legacy, migration Q3"

    def test_resolve_records_event(self, session, sample):
        item, _ = store.upsert_violation(session, sample)
        store.mark_resolved(session, item["pk"])
        events = audit_log.get_history(session, item["violation_id"])
        assert any(e["action"] == "resolve" for e in events)


class TestSparseIndex:
    def test_resolved_item_off_active_index(self, session, sample):
        """Resolved items must drop off active-pk-index so list/get_active skip them."""
        item, _ = store.upsert_violation(session, sample)
        assert item["pk"] in store.get_active_pks(session)
        store.mark_resolved(session, item["pk"])
        assert item["pk"] not in store.get_active_pks(session)

    def test_exempted_item_off_active_index(self, session, sample):
        item, _ = store.upsert_violation(session, sample)
        store.exempt(session, item["violation_id"], reason="approved exception")
        # Exempted items are not active — must not appear in active PKs
        assert item["pk"] not in store.get_active_pks(session)
