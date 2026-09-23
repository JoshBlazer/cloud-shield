"""
A scan that can't read something must neither invent findings nor resolve real ones.

This is what happens in production when CloudShieldAuditRole in a member account
lacks a permission (e.g. the role wasn't redeployed after new rules shipped), when
AWS throttles, or when assume-role fails.
"""

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from src.auditors.cloudtrail_auditor import CloudTrailAuditor
from src.auditors.iam_auditor import IAMAuditor
from src.auditors.s3_auditor import S3Auditor
from src.engine import evaluator
from src.store import violations as store

from tests.test_summary_and_paging import _create_violations_table


def _denied(op: str):
    def raiser(*_args, **_kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "not authorized"}}, op)
    return raiser


def _deny_on(monkeypatch, auditor_cls, method: str):
    """Make one client call on every new `auditor_cls` instance fail with AccessDenied."""
    original = auditor_cls.__init__

    def init(self, session):
        original(self, session)
        setattr(self._client, method, _denied(method))

    monkeypatch.setattr(auditor_cls, "__init__", init)


S3_RULES = [
    {"id": "S3_001", "name": "pab", "severity": "CRITICAL", "check": "public_access_block_disabled"},
    {"id": "S3_002", "name": "enc", "severity": "HIGH", "check": "encryption_disabled"},
    {"id": "S3_003", "name": "ver", "severity": "MEDIUM", "check": "versioning_disabled"},
]


@pytest.fixture
def session(aws_credentials):
    with mock_aws():
        yield boto3.Session(region_name="us-east-1")


# ── Auditors: unreadable ≠ non-compliant ─────────────────────────────────────

class TestAuditorsDontGuess:
    def test_s3_denied_setting_gives_no_verdict(self, session, monkeypatch):
        session.client("s3").create_bucket(Bucket="bucket-one")
        _deny_on(monkeypatch, S3Auditor, "get_bucket_encryption")
        auditor = S3Auditor(session)
        rule_ids = {v["rule_id"] for v in auditor.audit(S3_RULES)}
        assert "S3_002" not in rule_ids          # no false "encryption disabled"
        assert "S3_003" in rule_ids              # readable settings are still judged
        assert auditor.incomplete
        assert any("GetEncryptionConfiguration" in e for e in auditor.errors)

    def test_s3_list_denied_marks_incomplete(self, session, monkeypatch):
        _deny_on(monkeypatch, S3Auditor, "list_buckets")
        auditor = S3Auditor(session)
        assert auditor.audit(S3_RULES) == []
        assert auditor.incomplete

    def test_iam_password_policy_denied_gives_no_verdict(self, session, monkeypatch):
        _deny_on(monkeypatch, IAMAuditor, "get_account_password_policy")
        auditor = IAMAuditor(session)
        rules = [{"id": "IAM_003", "name": "pw", "severity": "HIGH", "check": "weak_password_policy"}]
        assert auditor.audit(rules) == []
        assert auditor.incomplete

    def test_iam_password_policy_absent_is_still_a_finding(self, session):
        rules = [{"id": "IAM_003", "name": "pw", "severity": "HIGH", "check": "weak_password_policy"}]
        auditor = IAMAuditor(session)
        assert [v["rule_id"] for v in auditor.audit(rules)] == ["IAM_003"]
        assert not auditor.incomplete

    def test_cloudtrail_denied_is_not_reported_as_missing(self, session, monkeypatch):
        _deny_on(monkeypatch, CloudTrailAuditor, "describe_trails")
        auditor = CloudTrailAuditor(session)
        rules = [{"id": "CT_001", "name": "ct", "severity": "CRITICAL", "check": "cloudtrail_not_enabled"}]
        assert auditor.audit(rules) == []
        assert auditor.incomplete


# ── Evaluator: reports incomplete scopes, survives crashes ───────────────────

class TestEvaluatorScopes:
    def test_reports_incomplete_scope(self, session, monkeypatch):
        _deny_on(monkeypatch, S3Auditor, "list_buckets")
        result = evaluator.run_audit(session=session, targets=[{"account_id": "111111111111", "region": "us-east-1"}])
        scopes = [(s["account_id"], s["region"], s["service"]) for s in result["incomplete_scopes"]]
        assert ("111111111111", "us-east-1", "s3") in scopes

    def test_crashing_auditor_does_not_sink_the_run(self, session, monkeypatch):
        def boom(self):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(S3Auditor, "fetch_resources", boom)
        result = evaluator.run_audit(session=session, targets=[{"account_id": "1", "region": "us-east-1"}])
        assert any(s["service"] == "s3" and "kaboom" in s["errors"][0] for s in result["incomplete_scopes"])
        # Other services still ran (an empty account still has account-level findings)
        assert {v["rule_id"].split("_")[0] for v in result["violations"]} - {"S3"}

    def test_assume_role_failure_marks_every_service(self, session):
        targets = [{"account_id": "999999999999", "region": "eu-west-1",
                    "role_arn": "arn:aws:iam::999999999999:role/DoesNotExist"}]
        # Moto's STS accepts any role, so force the failure explicitly.
        def fail(*_a, **_k):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "AssumeRole")
        orig = evaluator._assume_role_session
        evaluator._assume_role_session = fail
        try:
            result = evaluator.run_audit(session=session, targets=targets)
        finally:
            evaluator._assume_role_session = orig
        services = {s["service"] for s in result["incomplete_scopes"] if s["account_id"] == "999999999999"}
        assert services == set(evaluator.rule_services().values())

    def test_rule_services_covers_every_rule(self):
        mapping = evaluator.rule_services()
        assert mapping["S3_002"] == "s3" and mapping["CT_001"] == "cloudtrail" and mapping["EBS_003"] == "ebs"


# ── Handler: holds back resolution for findings it couldn't re-check ─────────

SUMMARY_NAME = "cloudshield-summary"
AUDIT_LOG    = "cloudshield-audit-log"


@pytest.fixture
def stack(aws_credentials, monkeypatch):
    monkeypatch.setenv("VIOLATIONS_TABLE", "cloudshield-violations")
    monkeypatch.setenv("AWS_ACCOUNT_ID", "123456789012")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AUDIT_TARGETS", "[]")
    with mock_aws():
        s = boto3.Session(region_name="us-east-1")
        _create_violations_table(s)
        ddb = s.resource("dynamodb")
        ddb.create_table(
            TableName=SUMMARY_NAME, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        )
        ddb.create_table(
            TableName=AUDIT_LOG, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "violation_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "violation_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
        )
        s.client("s3").create_bucket(Bucket="plain-bucket")
        yield s


def _status(session, pk):
    return session.resource("dynamodb").Table("cloudshield-violations").get_item(Key={"pk": pk})["Item"]["status"]


class TestHandlerHoldsBack:
    def test_denied_scan_does_not_resolve_existing_findings(self, stack, monkeypatch):
        from src.handler import lambda_handler

        first = lambda_handler({}, None)
        pk = "S3_002#plain-bucket"
        assert _status(stack, pk) == "OPEN"
        assert first["incomplete_scopes"] == []

        # Next run: the role lost s3:GetEncryptionConfiguration.
        _deny_on(monkeypatch, S3Auditor, "get_bucket_encryption")
        second = lambda_handler({}, None)
        assert _status(stack, pk) == "OPEN", "a finding we couldn't re-check must not be resolved"
        assert second["resolution_held_back"] >= 1
        assert any(s["service"] == "s3" for s in second["incomplete_scopes"])

        last = store.get_last_run(stack)
        assert last and last["held_back"] >= 1 and last["incomplete_scopes"]

    def test_complete_scan_still_resolves(self, stack):
        from src.handler import lambda_handler

        lambda_handler({}, None)
        stack.client("s3").put_bucket_encryption(
            Bucket="plain-bucket",
            ServerSideEncryptionConfiguration={"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
        )
        result = lambda_handler({}, None)
        assert _status(stack, "S3_002#plain-bucket") == "RESOLVED"
        assert result["resolution_held_back"] == 0
        assert store.get_last_run(stack)["incomplete_scopes"] == []

    def test_other_services_still_resolve_during_partial_outage(self, stack, monkeypatch):
        from src.handler import lambda_handler

        lambda_handler({}, None)
        # Fix EBS encryption-by-default while S3 is unreadable: EBS_002 must still resolve.
        stack.client("ec2").enable_ebs_encryption_by_default()
        _deny_on(monkeypatch, S3Auditor, "list_buckets")
        lambda_handler({}, None)
        assert _status(stack, "S3_002#plain-bucket") == "OPEN"
        ebs_pk = next(
            it["pk"] for it in stack.resource("dynamodb").Table("cloudshield-violations").scan()["Items"]
            if it["rule_id"] == "EBS_002"
        )
        assert _status(stack, ebs_pk) == "RESOLVED"
