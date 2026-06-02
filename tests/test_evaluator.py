"""Tests for the multi-account / multi-region evaluator orchestration."""

import boto3
import pytest
from moto import mock_aws
from src.engine import evaluator


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID",     "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN",    "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN",     "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION",    "us-east-1")
    monkeypatch.setenv("AWS_ACCOUNT_ID",        "111111111111")


class TestSingleAccount:
    def test_default_target_audits_current_account(self, aws_credentials):
        with mock_aws():
            session = boto3.Session(region_name="us-east-1")
            session.client("s3").create_bucket(Bucket="leaky-bucket")
            result = evaluator.run_audit(session=session, targets=None)
            assert result["resources_audited"] >= 1
            # Every violation must be tagged with the resolved account + region
            for v in result["violations"]:
                assert v["account_id"] == "111111111111"
                assert v["region"] == "us-east-1"

    def test_violations_carry_account_region(self, aws_credentials):
        with mock_aws():
            session = boto3.Session(region_name="us-east-1")
            session.client("s3").create_bucket(Bucket="another-leaky-bucket")
            targets = [{"account_id": "222222222222", "region": "eu-west-1"}]
            result = evaluator.run_audit(session=session, targets=targets)
            assert result["violations"]
            for v in result["violations"]:
                # explicit target metadata wins over env defaults
                assert v["account_id"] == "222222222222"
                assert v["region"] == "eu-west-1"


class TestMultiTarget:
    def test_aggregates_across_targets(self, aws_credentials):
        with mock_aws():
            session = boto3.Session(region_name="us-east-1")
            session.client("s3").create_bucket(Bucket="shared-bucket")
            # Two targets with no role_arn → both reuse the same session
            targets = [
                {"account_id": "111111111111", "region": "us-east-1"},
                {"account_id": "111111111111", "region": "us-west-2"},
            ]
            result = evaluator.run_audit(session=session, targets=targets)
            # Same bucket audited twice (once per target) → resources counted per target
            assert result["resources_audited"] >= 2

    def test_assume_role_failure_skips_target(self, aws_credentials):
        with mock_aws():
            session = boto3.Session(region_name="us-east-1")
            session.client("s3").create_bucket(Bucket="local-bucket")
            targets = [
                {"account_id": "111111111111", "region": "us-east-1"},
                # Bad role ARN → assume_role raises → target skipped, run continues
                {"account_id": "999999999999", "region": "us-east-1",
                 "role_arn": "arn:aws:iam::999999999999:role/DoesNotExist"},
            ]
            result = evaluator.run_audit(session=session, targets=targets)
            # First target still produced results despite the second failing
            assert result["resources_audited"] >= 1


class TestTargetParsing:
    def test_env_var_targets(self, aws_credentials, monkeypatch):
        monkeypatch.setenv("AUDIT_TARGETS", '[{"account_id":"333","region":"us-east-1"}]')
        with mock_aws():
            session = boto3.Session(region_name="us-east-1")
            session.client("s3").create_bucket(Bucket="env-bucket")
            result = evaluator.run_audit(session=session)  # targets=None → read env
            for v in result["violations"]:
                assert v["account_id"] == "333"

    def test_malformed_env_falls_back(self, aws_credentials, monkeypatch):
        monkeypatch.setenv("AUDIT_TARGETS", "not-json{{{")
        with mock_aws():
            session = boto3.Session(region_name="us-east-1")
            session.client("s3").create_bucket(Bucket="fallback-bucket")
            result = evaluator.run_audit(session=session)
            # Falls back to default single-account target — still runs
            assert result["resources_audited"] >= 1
