"""Shared pytest fixtures using Moto to spin up a fake AWS environment."""

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(scope="function")
def aws_credentials(monkeypatch):
    """Inject dummy credentials so Moto intercepts all boto3 calls."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(scope="function")
def mock_s3_session(aws_credentials):
    with mock_aws():
        yield boto3.Session(region_name="us-east-1")


@pytest.fixture(scope="function")
def mock_ec2_session(aws_credentials):
    with mock_aws():
        yield boto3.Session(region_name="us-east-1")


@pytest.fixture(scope="function")
def mock_iam_session(aws_credentials):
    with mock_aws():
        yield boto3.Session(region_name="us-east-1")


@pytest.fixture(scope="function")
def s3_rules():
    return [
        {
            "id": "S3_001",
            "name": "No Public S3 Buckets",
            "severity": "CRITICAL",
            "check": "public_access_block_disabled",
        },
        {
            "id": "S3_002",
            "name": "S3 Server-Side Encryption Required",
            "severity": "HIGH",
            "check": "encryption_disabled",
        },
        {
            "id": "S3_003",
            "name": "S3 Versioning Required",
            "severity": "MEDIUM",
            "check": "versioning_disabled",
        },
        {
            "id": "S3_004",
            "name": "Bucket Policy Grants Public Access",
            "severity": "CRITICAL",
            "check": "bucket_policy_public",
        },
    ]


@pytest.fixture(scope="function")
def iam_rules():
    return [
        {
            "id": "IAM_001",
            "name": "MFA Required for Console Users",
            "severity": "CRITICAL",
            "check": "mfa_not_enabled",
        },
        {
            "id": "IAM_002",
            "name": "Access Key Rotation Required",
            "severity": "HIGH",
            "check": "access_key_not_rotated",
            "max_age_days": 90,
        },
        {
            "id": "IAM_003",
            "name": "Weak Account Password Policy",
            "severity": "HIGH",
            "check": "weak_password_policy",
            "min_length": 14,
            "require_uppercase": True,
            "require_lowercase": True,
            "require_numbers": True,
            "require_symbols": True,
            "max_age_days": 90,
            "prevent_reuse": 5,
        },
        {
            "id": "IAM_004",
            "name": "Root Account MFA Not Enabled",
            "severity": "CRITICAL",
            "check": "root_mfa_disabled",
        },
    ]


@pytest.fixture(scope="function")
def ec2_rules():
    return [
        {
            "id": "EC2_001",
            "name": "No Unrestricted SSH Access",
            "severity": "CRITICAL",
            "check": "unrestricted_ingress",
            "port": 22,
        },
        {
            "id": "EC2_002",
            "name": "No Unrestricted RDP Access",
            "severity": "CRITICAL",
            "check": "unrestricted_ingress",
            "port": 3389,
        },
        {
            "id": "EC2_003",
            "name": "No Unrestricted All Traffic",
            "severity": "CRITICAL",
            "check": "unrestricted_all_traffic",
        },
    ]
