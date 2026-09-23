"""Moto-backed tests for the CloudTrail, RDS, KMS, and EBS auditors."""

import boto3
import pytest
from moto import mock_aws
from src.auditors.cloudtrail_auditor import CloudTrailAuditor
from src.auditors.ebs_auditor import EBSAuditor
from src.auditors.kms_auditor import KMSAuditor
from src.auditors.rds_auditor import RDSAuditor

ACCOUNT = "123456789012"  # Moto's default account


@pytest.fixture
def session(aws_credentials):
    with mock_aws():
        yield boto3.Session(region_name="us-east-1")


def _rule(rule_id: str, check: str, severity: str = "HIGH", **extra):
    return {"id": rule_id, "name": rule_id, "severity": severity, "check": check, **extra}


# ── CloudTrail ────────────────────────────────────────────────────────────────

CT_RULES = [
    _rule("CT_001", "cloudtrail_not_enabled", "CRITICAL"),
    _rule("CT_002", "log_file_validation_disabled"),
    _rule("CT_003", "trail_not_kms_encrypted", "MEDIUM"),
]


class TestCloudTrailAuditor:
    def _trail(self, session, name="org-trail", multi_region=True, validation=False, log=True):
        session.client("s3").create_bucket(Bucket=f"{name}-logs")
        ct = session.client("cloudtrail")
        ct.create_trail(
            Name=name,
            S3BucketName=f"{name}-logs",
            IsMultiRegionTrail=multi_region,
            EnableLogFileValidation=validation,
        )
        if log:
            ct.start_logging(Name=name)

    def test_no_trail_flags_account(self, session):
        violations = CloudTrailAuditor(session).audit(CT_RULES)
        assert [v["rule_id"] for v in violations] == ["CT_001"]
        v = violations[0]
        assert v["resource_type"] == "AWS::::Account"
        assert v["resource_id"] == f"{ACCOUNT}:us-east-1:cloudtrail"

    def test_trail_not_logging_is_not_coverage(self, session):
        self._trail(session, log=False)
        rule_ids = {v["rule_id"] for v in CloudTrailAuditor(session).audit(CT_RULES)}
        assert "CT_001" in rule_ids

    def test_logging_trail_satisfies_coverage(self, session):
        self._trail(session)
        rule_ids = {v["rule_id"] for v in CloudTrailAuditor(session).audit(CT_RULES)}
        assert "CT_001" not in rule_ids

    def test_flags_validation_and_encryption_per_trail(self, session):
        self._trail(session, validation=False)
        violations = CloudTrailAuditor(session).audit(CT_RULES)
        by_rule = {v["rule_id"]: v for v in violations}
        assert set(by_rule) == {"CT_002", "CT_003"}
        assert by_rule["CT_002"]["resource_type"] == "AWS::CloudTrail::Trail"
        assert by_rule["CT_002"]["resource_id"].startswith("arn:aws:cloudtrail:")

    def test_validation_enabled_is_compliant(self, session):
        self._trail(session, validation=True)
        rule_ids = {v["rule_id"] for v in CloudTrailAuditor(session).audit(CT_RULES)}
        assert "CT_002" not in rule_ids

    def test_shadow_trail_counts_for_coverage_but_not_hardening(self, session):
        # Multi-region trail homed in us-east-1, audited from eu-west-1
        self._trail(session, validation=False)
        eu = boto3.Session(region_name="eu-west-1")
        violations = CloudTrailAuditor(eu).audit(CT_RULES)
        assert violations == []

    def test_evaluate_uses_is_home_flag(self, session):
        trails = [{
            "Name": "shadow", "TrailARN": "arn:aws:cloudtrail:us-west-2:1:trail/shadow",
            "IsMultiRegionTrail": True, "IsLogging": True, "IsHome": False,
        }]
        assert CloudTrailAuditor(session).evaluate(trails, CT_RULES) == []


# ── RDS ───────────────────────────────────────────────────────────────────────

RDS_RULES = [
    _rule("RDS_001", "rds_publicly_accessible", "CRITICAL"),
    _rule("RDS_002", "rds_storage_unencrypted"),
    _rule("RDS_003", "rds_backup_retention_low", "MEDIUM", min_days=7),
]


class TestRDSAuditor:
    def _db(self, session, name, **kwargs):
        params = {
            "DBInstanceIdentifier": name,
            "DBInstanceClass": "db.t3.micro",
            "Engine": "postgres",
            "MasterUsername": "admin",
            "MasterUserPassword": "password123!",
            "AllocatedStorage": 20,
            "PubliclyAccessible": False,
            "StorageEncrypted": True,
            "BackupRetentionPeriod": 7,
            "Tags": [{"Key": "team", "Value": "payments"}],
        }
        params.update(kwargs)
        session.client("rds").create_db_instance(**params)

    def test_compliant_instance_has_no_violations(self, session):
        self._db(session, "good-db")
        assert RDSAuditor(session).audit(RDS_RULES) == []

    def test_flags_public_unencrypted_short_retention(self, session):
        self._db(
            session, "bad-db",
            PubliclyAccessible=True, StorageEncrypted=False, BackupRetentionPeriod=1,
        )
        violations = RDSAuditor(session).audit(RDS_RULES)
        assert {v["rule_id"] for v in violations} == {"RDS_001", "RDS_002", "RDS_003"}
        v = violations[0]
        assert v["resource_type"] == "AWS::RDS::DBInstance"
        assert v["resource_id"].endswith(":db:bad-db")
        assert v["team"] == "payments"

    def test_retention_threshold_is_configurable(self, session):
        self._db(session, "db", BackupRetentionPeriod=10)
        rules = [_rule("RDS_003", "rds_backup_retention_low", min_days=14)]
        violations = RDSAuditor(session).audit(rules)
        assert len(violations) == 1
        assert "10 day(s); minimum is 14" in violations[0]["reason"]

    def test_empty_account(self, session):
        assert RDSAuditor(session).audit(RDS_RULES) == []


# ── KMS ───────────────────────────────────────────────────────────────────────

KMS_RULES = [_rule("KMS_001", "kms_rotation_disabled", "MEDIUM")]


class TestKMSAuditor:
    def test_flags_customer_key_without_rotation(self, session):
        key = session.client("kms").create_key(
            Tags=[{"TagKey": "team", "TagValue": "security"}]
        )["KeyMetadata"]
        violations = KMSAuditor(session).audit(KMS_RULES)
        assert len(violations) == 1
        assert violations[0]["resource_id"] == key["Arn"]
        assert violations[0]["resource_type"] == "AWS::KMS::Key"
        assert violations[0]["team"] == "security"

    def test_rotation_enabled_is_compliant(self, session):
        kms = session.client("kms")
        key_id = kms.create_key()["KeyMetadata"]["KeyId"]
        kms.enable_key_rotation(KeyId=key_id)
        assert KMSAuditor(session).audit(KMS_RULES) == []

    def test_skips_asymmetric_and_disabled_keys(self, session):
        kms = session.client("kms")
        kms.create_key(KeySpec="RSA_2048", KeyUsage="SIGN_VERIFY")
        disabled = kms.create_key()["KeyMetadata"]["KeyId"]
        kms.disable_key(KeyId=disabled)
        assert KMSAuditor(session).audit(KMS_RULES) == []


# ── EBS ───────────────────────────────────────────────────────────────────────

EBS_RULES = [
    _rule("EBS_001", "ebs_volume_unencrypted"),
    _rule("EBS_002", "ebs_default_encryption_disabled", "MEDIUM"),
    _rule("EBS_003", "ebs_snapshot_public", "CRITICAL"),
]


class TestEBSAuditor:
    def test_default_encryption_disabled_flags_account(self, session):
        violations = EBSAuditor(session).audit(EBS_RULES)
        assert [v["rule_id"] for v in violations] == ["EBS_002"]
        assert violations[0]["resource_id"] == f"{ACCOUNT}:us-east-1:ebs-encryption-by-default"

    def test_default_encryption_enabled_is_compliant(self, session):
        session.client("ec2").enable_ebs_encryption_by_default()
        assert EBSAuditor(session).audit(EBS_RULES) == []

    def test_flags_unencrypted_volume_with_team(self, session):
        ec2 = session.client("ec2")
        ec2.enable_ebs_encryption_by_default()
        vol = ec2.create_volume(
            AvailabilityZone="us-east-1a", Size=8, Encrypted=False,
            TagSpecifications=[{
                "ResourceType": "volume", "Tags": [{"Key": "team", "Value": "infra"}],
            }],
        )
        violations = EBSAuditor(session).audit(EBS_RULES)
        assert [(v["rule_id"], v["resource_id"]) for v in violations] == [
            ("EBS_001", vol["VolumeId"])
        ]
        assert violations[0]["team"] == "infra"

    def test_encrypted_volume_is_compliant(self, session):
        ec2 = session.client("ec2")
        ec2.enable_ebs_encryption_by_default()
        ec2.create_volume(AvailabilityZone="us-east-1a", Size=8, Encrypted=True)
        assert EBSAuditor(session).audit(EBS_RULES) == []

    def test_flags_public_snapshot_only(self, session):
        ec2 = session.client("ec2")
        ec2.enable_ebs_encryption_by_default()
        vol = ec2.create_volume(AvailabilityZone="us-east-1a", Size=8, Encrypted=True)
        public = ec2.create_snapshot(VolumeId=vol["VolumeId"])["SnapshotId"]
        ec2.create_snapshot(VolumeId=vol["VolumeId"])  # private sibling
        ec2.modify_snapshot_attribute(
            SnapshotId=public, Attribute="createVolumePermission",
            OperationType="add", GroupNames=["all"],
        )
        violations = EBSAuditor(session).audit(EBS_RULES)
        assert [(v["rule_id"], v["resource_id"]) for v in violations] == [("EBS_003", public)]
        assert violations[0]["resource_type"] == "AWS::EC2::Snapshot"
