"""Integration tests for the API Lambda handler."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
def api_session(aws_credentials):
    with mock_aws():
        session = boto3.Session(region_name="us-east-1")
        ddb = session.resource("dynamodb")
        ddb.create_table(
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

        # Seed two violations
        store.upsert_violation(session, {
            "rule_id": "S3_001", "rule_name": "Public S3", "severity": "CRITICAL",
            "resource_type": "AWS::S3::Bucket", "resource_id": "bucket-a",
            "reason": "public", "team": "data",
        })
        store.upsert_violation(session, {
            "rule_id": "EC2_001", "rule_name": "SSH Open", "severity": "CRITICAL",
            "resource_type": "AWS::EC2::SecurityGroup", "resource_id": "sg-x",
            "reason": "ssh open", "team": "infra",
        })

        yield session


def _event(method: str, path: str, qs: dict | None = None, body: dict | None = None) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "queryStringParameters": qs,
        "body": json.dumps(body) if body else None,
    }


def _call(method, path, qs=None, body=None):
    from src.api.handler import api_handler
    return api_handler(_event(method, path, qs, body), None)


class TestListViolations:
    def test_returns_200(self, api_session):
        resp = _call("GET", "/violations")
        assert resp["statusCode"] == 200

    def test_returns_all_violations(self, api_session):
        body = json.loads(_call("GET", "/violations")["body"])
        assert body["count"] == 2

    def test_filter_by_status(self, api_session):
        body = json.loads(_call("GET", "/violations", qs={"status": "OPEN"})["body"])
        assert all(v["status"] == "OPEN" for v in body["violations"])

    def test_filter_by_team(self, api_session):
        body = json.loads(_call("GET", "/violations", qs={"team": "infra"})["body"])
        assert body["count"] == 1
        assert body["violations"][0]["resource_id"] == "sg-x"

    def test_cors_headers_present(self, api_session):
        resp = _call("GET", "/violations")
        assert "Access-Control-Allow-Origin" in resp["headers"]

    def test_last_page_has_null_cursor(self, api_session):
        body = json.loads(_call("GET", "/violations")["body"])
        assert body["next_cursor"] is None

    def test_cursor_pages_through_results(self, api_session):
        first = json.loads(_call("GET", "/violations", qs={"limit": "1"})["body"])
        assert first["count"] == 1
        assert first["next_cursor"]
        second = json.loads(_call(
            "GET", "/violations", qs={"limit": "1", "cursor": first["next_cursor"]},
        )["body"])
        ids = {first["violations"][0]["pk"], second["violations"][0]["pk"]}
        assert ids == {"S3_001#bucket-a", "EC2_001#sg-x"}

    def test_invalid_cursor_returns_400(self, api_session):
        resp = _call("GET", "/violations", qs={"cursor": "not-a-cursor!"})
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "invalid cursor"


class TestGetViolation:
    def test_returns_violation(self, api_session):
        # Get list first to find a valid ID
        body = json.loads(_call("GET", "/violations")["body"])
        vid = body["violations"][0]["violation_id"]
        resp = _call("GET", f"/violations/{vid}")
        assert resp["statusCode"] == 200
        fetched = json.loads(resp["body"])
        assert fetched["violation_id"] == vid

    def test_returns_404_for_unknown(self, api_session):
        resp = _call("GET", "/violations/nonexistent-id")
        assert resp["statusCode"] == 404


class TestPatchViolation:
    def _get_first_id(self):
        body = json.loads(_call("GET", "/violations")["body"])
        return body["violations"][0]["violation_id"]

    def test_acknowledge(self, api_session):
        vid = self._get_first_id()
        resp = _call("PATCH", f"/violations/{vid}", body={"action": "acknowledge", "by": "tester"})
        assert resp["statusCode"] == 200
        item = store.get_by_id(boto3.Session(region_name="us-east-1"), vid)
        assert item["status"] == "ACKNOWLEDGED"

    def test_snooze(self, api_session):
        vid = self._get_first_id()
        resp = _call("PATCH", f"/violations/{vid}", body={"action": "snooze", "days": 14})
        assert resp["statusCode"] == 200

    def test_exempt(self, api_session):
        vid = self._get_first_id()
        resp = _call("PATCH", f"/violations/{vid}", body={"action": "exempt", "reason": "planned"})
        assert resp["statusCode"] == 200

    def test_unknown_action_returns_400(self, api_session):
        vid = self._get_first_id()
        resp = _call("PATCH", f"/violations/{vid}", body={"action": "delete_everything"})
        assert resp["statusCode"] == 400

    def test_nonexistent_violation_returns_404(self, api_session):
        resp = _call("PATCH", "/violations/fake-id", body={"action": "acknowledge"})
        assert resp["statusCode"] == 404


class TestSummary:
    def test_returns_200(self, api_session):
        resp = _call("GET", "/summary")
        assert resp["statusCode"] == 200

    def test_summary_structure(self, api_session):
        body = json.loads(_call("GET", "/summary")["body"])
        assert "total" in body
        assert "by_status" in body
        assert "by_severity" in body
        assert "by_team" in body
        assert body["total"] == 2


class TestReopen:
    def _first(self):
        return json.loads(_call("GET", "/violations")["body"])["violations"][0]["violation_id"]

    def test_reopen_acknowledged_returns_200(self, api_session):
        vid = self._first()
        _call("PATCH", f"/violations/{vid}", body={"action": "acknowledge"})
        resp = _call("PATCH", f"/violations/{vid}", body={"action": "reopen", "by": "tester"})
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"]) == {"ok": True, "action": "reopen", "violation_id": vid}
        assert store.get_by_id(api_session, vid)["status"] == "OPEN"

    def test_reopen_open_returns_409(self, api_session):
        resp = _call("PATCH", f"/violations/{self._first()}", body={"action": "reopen"})
        assert resp["statusCode"] == 409
        assert json.loads(resp["body"]) == {"error": "violation cannot be reopened"}

    def test_reopen_resolved_returns_409(self, api_session):
        vid = self._first()
        store.mark_resolved(api_session, store.get_by_id(api_session, vid)["pk"])
        resp = _call("PATCH", f"/violations/{vid}", body={"action": "reopen"})
        assert resp["statusCode"] == 409

    def test_reopen_unknown_returns_404(self, api_session):
        resp = _call("PATCH", "/violations/fake-id", body={"action": "reopen"})
        assert resp["statusCode"] == 404


@pytest.fixture
def trend_session(api_session):
    ddb = api_session.resource("dynamodb")
    ddb.create_table(
        TableName=store.SUMMARY_TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
    )
    today = datetime.now(tz=UTC).date()
    for offset in (0, 1, 20):
        ddb.Table(store.SUMMARY_TABLE).put_item(Item={
            "pk": f"trend#{(today - timedelta(days=offset)).isoformat()}",
            "CRITICAL": 3, "HIGH": 1, "MEDIUM": 0, "LOW": 0, "total_active": 4,
            "recorded_at": "x",
        })
    return today


class TestTrend:
    def test_default_window_is_14_days(self, trend_session):
        resp = _call("GET", "/trend")
        assert resp["statusCode"] == 200
        days = json.loads(resp["body"])["days"]
        assert [d["date"] for d in days] == [
            (trend_session - timedelta(days=1)).isoformat(), trend_session.isoformat(),
        ]
        assert days[-1] == {
            "date": trend_session.isoformat(),
            "CRITICAL": 3, "HIGH": 1, "MEDIUM": 0, "LOW": 0, "total_active": 4,
        }

    def test_days_param(self, trend_session):
        body = json.loads(_call("GET", "/trend", qs={"days": "30"})["body"])
        assert len(body["days"]) == 3

    @pytest.mark.parametrize(("raw", "expected"), [("0", 1), ("-5", 1), ("1000", 3)])
    def test_days_clamped(self, trend_session, raw, expected):
        resp = _call("GET", "/trend", qs={"days": raw})
        assert resp["statusCode"] == 200
        assert len(json.loads(resp["body"])["days"]) == expected

    @pytest.mark.parametrize("raw", ["abc", "1.5", ""])
    def test_invalid_days_returns_400(self, trend_session, raw):
        resp = _call("GET", "/trend", qs={"days": raw})
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid days"}

    def test_requires_auth(self, trend_session, monkeypatch):
        from src.api import handler
        monkeypatch.setattr(handler.secrets, "get_secret", lambda name: "k" if name == "api_key" else "")
        assert _call("GET", "/trend")["statusCode"] == 401


class TestJsonEncoding:
    def test_decimals_encode_as_numbers(self, api_session):
        body = json.loads(_call("GET", "/violations")["body"])
        assert body["violations"][0]["occurrence_count"] == 1
        assert isinstance(body["violations"][0]["occurrence_count"], int)

    def test_resolved_ttl_is_int(self, api_session):
        vid = json.loads(_call("GET", "/violations")["body"])["violations"][0]["violation_id"]
        store.mark_resolved(api_session, store.get_by_id(api_session, vid)["pk"])
        item = json.loads(_call("GET", f"/violations/{vid}")["body"])
        assert isinstance(item["ttl"], int)

    def test_default_handles_other_types(self):
        from src.api.handler import _json_default
        assert _json_default(Decimal("2")) == 2
        assert _json_default(Decimal("2.5")) == 2.5
        assert _json_default(datetime(2026, 9, 10, tzinfo=UTC)) == "2026-09-10 00:00:00+00:00"


class TestCors:
    def test_options_preflight(self, api_session):
        resp = _call("OPTIONS", "/violations")
        assert resp["statusCode"] == 200
        assert "Access-Control-Allow-Origin" in resp["headers"]

    def test_404_on_unknown_route(self, api_session):
        resp = _call("GET", "/nonexistent")
        assert resp["statusCode"] == 404
