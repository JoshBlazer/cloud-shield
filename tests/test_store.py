"""Tests for the DynamoDB violation store."""

import boto3
import pytest
from moto import mock_aws
from src.store import violations as store

TABLE_NAME = "cloudshield-violations"


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID",     "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN",    "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN",     "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION",    "us-east-1")
    monkeypatch.setenv("VIOLATIONS_TABLE",      TABLE_NAME)


@pytest.fixture
def ddb_session(aws_credentials):
    with mock_aws():
        session = boto3.Session(region_name="us-east-1")
        ddb = session.resource("dynamodb")
        ddb.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "pk",           "AttributeType": "S"},
                {"AttributeName": "violation_id", "AttributeType": "S"},
                {"AttributeName": "status",       "AttributeType": "S"},
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
                    "IndexName": "status-index",
                    "KeySchema": [
                        {"AttributeName": "status",    "KeyType": "HASH"},
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
        yield session


@pytest.fixture
def sample_violation():
    return {
        "rule_id":       "S3_001",
        "rule_name":     "No Public S3 Buckets",
        "severity":      "CRITICAL",
        "resource_type": "AWS::S3::Bucket",
        "resource_id":   "my-bucket",
        "reason":        "Public access block is not fully enabled",
        "team":          "data-platform",
        "owner":         "alice@acme.com",
    }


# ── upsert ───────────────────────────────────────────────────────────────────

class TestUpsert:
    def test_creates_new_violation(self, ddb_session, sample_violation):
        item, is_new = store.upsert_violation(ddb_session, sample_violation)
        assert is_new is True
        assert item["rule_id"] == "S3_001"
        assert item["status"] == store.STATUS_OPEN
        assert item["occurrence_count"] == 1
        assert item["team"] == "data-platform"

    def test_existing_active_returns_false(self, ddb_session, sample_violation):
        store.upsert_violation(ddb_session, sample_violation)
        _, is_new = store.upsert_violation(ddb_session, sample_violation)
        assert is_new is False

    def test_existing_updates_occurrence_count(self, ddb_session, sample_violation):
        store.upsert_violation(ddb_session, sample_violation)
        item, _ = store.upsert_violation(ddb_session, sample_violation)
        assert item["occurrence_count"] == 2

    def test_resolved_violation_creates_new(self, ddb_session, sample_violation):
        item, _ = store.upsert_violation(ddb_session, sample_violation)
        pk = item["pk"]
        store.mark_resolved(ddb_session, pk)
        _, is_new = store.upsert_violation(ddb_session, sample_violation)
        assert is_new is True

    def test_stable_violation_id(self, ddb_session, sample_violation):
        item1, _ = store.upsert_violation(ddb_session, sample_violation)
        store.mark_resolved(ddb_session, item1["pk"])
        item2, _ = store.upsert_violation(ddb_session, sample_violation)
        assert item1["violation_id"] == item2["violation_id"]

    def test_team_from_violation_dict(self, ddb_session, sample_violation):
        item, _ = store.upsert_violation(ddb_session, sample_violation)
        assert item["team"] == "data-platform"

    def test_team_fallback_to_untagged(self, ddb_session):
        v = {
            "rule_id": "EC2_001", "rule_name": "SSH", "severity": "CRITICAL",
            "resource_type": "AWS::EC2::SecurityGroup", "resource_id": "sg-abc",
            "reason": "port 22 open",
        }
        item, _ = store.upsert_violation(ddb_session, v)
        assert item["team"] == "untagged"


# ── lifecycle operations ──────────────────────────────────────────────────────

class TestLifecycle:
    def _seed(self, session, violation):
        item, _ = store.upsert_violation(session, violation)
        return item["violation_id"]

    def test_acknowledge(self, ddb_session, sample_violation):
        vid = self._seed(ddb_session, sample_violation)
        ok = store.acknowledge(ddb_session, vid, by="reviewer@acme.com")
        assert ok is True
        item = store.get_by_id(ddb_session, vid)
        assert item["status"] == store.STATUS_ACKNOWLEDGED
        assert item["acknowledged_by"] == "reviewer@acme.com"

    def test_snooze(self, ddb_session, sample_violation):
        vid = self._seed(ddb_session, sample_violation)
        ok = store.snooze(ddb_session, vid, days=7)
        assert ok is True
        item = store.get_by_id(ddb_session, vid)
        assert item["status"] == store.STATUS_SNOOZED
        assert item["snooze_until"] is not None

    def test_exempt(self, ddb_session, sample_violation):
        vid = self._seed(ddb_session, sample_violation)
        ok = store.exempt(ddb_session, vid, reason="legacy bucket, migration Q3")
        assert ok is True
        item = store.get_by_id(ddb_session, vid)
        assert item["status"] == store.STATUS_EXEMPTED
        assert item["exempt_reason"] == "legacy bucket, migration Q3"

    def test_mark_resolved(self, ddb_session, sample_violation):
        item, _ = store.upsert_violation(ddb_session, sample_violation)
        store.mark_resolved(ddb_session, item["pk"])
        fetched = store.get_by_id(ddb_session, item["violation_id"])
        assert fetched["status"] == store.STATUS_RESOLVED
        assert fetched["resolved_at"] is not None

    def test_mark_resolved_idempotent(self, ddb_session, sample_violation):
        item, _ = store.upsert_violation(ddb_session, sample_violation)
        store.mark_resolved(ddb_session, item["pk"])
        store.mark_resolved(ddb_session, item["pk"])  # should not raise

    def test_acknowledge_nonexistent_returns_false(self, ddb_session):
        assert store.acknowledge(ddb_session, "nonexistent-id") is False

    def test_snooze_nonexistent_returns_false(self, ddb_session):
        assert store.snooze(ddb_session, "nonexistent-id") is False

    def test_exemption_survives_reaudit(self, ddb_session, sample_violation):
        """Exempted violations must not be recreated or re-alert when still detected."""
        item, _ = store.upsert_violation(ddb_session, sample_violation)
        vid = item["violation_id"]
        store.exempt(ddb_session, vid, reason="legacy bucket, migration Q3")

        # Simulate the next hourly audit finding the same violation still failing
        _, is_new = store.upsert_violation(ddb_session, sample_violation)

        assert is_new is False, "exempted violation must not fire a new alert"
        refetched = store.get_by_id(ddb_session, vid)
        assert refetched["status"] == store.STATUS_EXEMPTED, "status must remain EXEMPTED"
        assert refetched["occurrence_count"] == 2  # last_seen + occurrence bumped silently

    def test_snooze_wakeup_reopens_expired_item(self, ddb_session, sample_violation):
        """Violations past their snooze_until must flip back to OPEN."""
        from datetime import UTC, datetime, timedelta

        item, _ = store.upsert_violation(ddb_session, sample_violation)
        store.snooze(ddb_session, item["violation_id"], days=7)

        # Backdate snooze_until to yesterday so the item is now overdue
        past = (datetime.now(tz=UTC) - timedelta(days=1)).isoformat()
        ddb_session.resource("dynamodb").Table("cloudshield-violations").update_item(
            Key={"pk": item["pk"]},
            UpdateExpression="SET snooze_until = :p",
            ExpressionAttributeValues={":p": past},
        )

        woken = store.wake_snoozed_violations(ddb_session)
        assert woken == 1
        refetched = store.get_by_id(ddb_session, item["violation_id"])
        assert refetched["status"] == store.STATUS_OPEN

    def test_active_snooze_not_woken(self, ddb_session, sample_violation):
        """Violations snoozed until the future must remain SNOOZED."""
        item, _ = store.upsert_violation(ddb_session, sample_violation)
        store.snooze(ddb_session, item["violation_id"], days=7)

        woken = store.wake_snoozed_violations(ddb_session)
        assert woken == 0
        refetched = store.get_by_id(ddb_session, item["violation_id"])
        assert refetched["status"] == store.STATUS_SNOOZED


# ── read operations ───────────────────────────────────────────────────────────

class TestReads:
    def _seed_many(self, session):
        violations = [
            {"rule_id": "S3_001", "rule_name": "Public S3", "severity": "CRITICAL",
             "resource_type": "AWS::S3::Bucket", "resource_id": "bucket-a",
             "reason": "public", "team": "data"},
            {"rule_id": "EC2_001", "rule_name": "SSH Open", "severity": "CRITICAL",
             "resource_type": "AWS::EC2::SecurityGroup", "resource_id": "sg-x",
             "reason": "ssh", "team": "infra"},
            {"rule_id": "IAM_001", "rule_name": "No MFA", "severity": "CRITICAL",
             "resource_type": "AWS::IAM::User", "resource_id": "alice",
             "reason": "no mfa", "team": "infra"},
        ]
        items = []
        for v in violations:
            item, _ = store.upsert_violation(session, v)
            items.append(item)
        return items

    def test_list_all(self, ddb_session):
        self._seed_many(ddb_session)
        items = store.list_violations(ddb_session)
        assert len(items) == 3

    def test_list_by_status(self, ddb_session):
        items = self._seed_many(ddb_session)
        store.acknowledge(ddb_session, items[0]["violation_id"])
        open_items = store.list_violations(ddb_session, status="OPEN")
        assert all(i["status"] == "OPEN" for i in open_items)
        assert len(open_items) == 2

    def test_list_by_team(self, ddb_session):
        self._seed_many(ddb_session)
        infra_items = store.list_violations(ddb_session, team="infra")
        assert len(infra_items) == 2
        assert all(i["team"] == "infra" for i in infra_items)

    def test_get_by_id(self, ddb_session, sample_violation):
        item, _ = store.upsert_violation(ddb_session, sample_violation)
        fetched = store.get_by_id(ddb_session, item["violation_id"])
        assert fetched is not None
        assert fetched["rule_id"] == "S3_001"

    def test_get_by_id_nonexistent(self, ddb_session):
        assert store.get_by_id(ddb_session, "does-not-exist") is None

    def test_get_active_pks(self, ddb_session):
        items = self._seed_many(ddb_session)
        store.mark_resolved(ddb_session, items[0]["pk"])
        pks = store.get_active_pks(ddb_session)
        assert len(pks) == 2
        assert items[0]["pk"] not in pks

    def test_get_summary(self, ddb_session):
        items = self._seed_many(ddb_session)
        store.acknowledge(ddb_session, items[0]["violation_id"])
        summary = store.get_summary(ddb_session)
        assert summary["total"] == 3
        assert summary["by_status"]["OPEN"] == 2
        assert summary["by_status"]["ACKNOWLEDGED"] == 1
        assert summary["by_team"]["infra"]["OPEN"] == 2
