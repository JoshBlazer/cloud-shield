"""
Local end-to-end runner for CloudShield-Auditor.

Boots a fake AWS environment via Moto, seeds it with realistic
violations, fires the Lambda handler, and prints every structured
log line plus the handler's return value.

Run:  python scripts/local_run.py
"""

import json
import os
import sys
from pathlib import Path

# Make sure the project root is on the path regardless of where we're invoked from
sys.path.insert(0, str(Path(__file__).parent.parent))

# Inject dummy creds so boto3 doesn't reach out to real AWS
os.environ.update(
    {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "SNS_TOPIC_ARN": "",          # set after topic creation below
        "CLOUDWATCH_NAMESPACE": "CloudShield/Auditor",
        "AWS_REGION": "us-east-1",
    }
)

import boto3
from moto import mock_aws

REGION = "us-east-1"
DIVIDER = "-" * 72


def seed_violations(session):
    """Create a handful of intentionally misconfigured resources."""
    s3  = session.client("s3")
    ec2 = session.client("ec2")
    iam = session.client("iam")

    # ── S3 ────────────────────────────────────────────────────────────────
    # Bucket 1: totally open — no public-access block, no encryption, no versioning
    s3.create_bucket(Bucket="acme-raw-data-prod")

    # Bucket 2: encrypted + versioned but public-access block missing
    s3.create_bucket(Bucket="acme-uploads-prod")
    s3.put_bucket_encryption(
        Bucket="acme-uploads-prod",
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    s3.put_bucket_versioning(
        Bucket="acme-uploads-prod",
        VersioningConfiguration={"Status": "Enabled"},
    )

    # Bucket 3: fully compliant — should produce zero violations
    s3.create_bucket(Bucket="acme-backups-prod")
    s3.put_public_access_block(
        Bucket="acme-backups-prod",
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket="acme-backups-prod",
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    s3.put_bucket_versioning(
        Bucket="acme-backups-prod",
        VersioningConfiguration={"Status": "Enabled"},
    )

    # ── EC2 / Security Groups ─────────────────────────────────────────────
    # SG 1: SSH wide open to the internet
    resp = ec2.create_security_group(
        GroupName="web-tier-sg", Description="Web tier — SSH left open by mistake"
    )
    ec2.authorize_security_group_ingress(
        GroupId=resp["GroupId"],
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "oops"}],
            }
        ],
    )

    # SG 2: allows all traffic (IpProtocol -1) to the internet
    resp2 = ec2.create_security_group(
        GroupName="dev-sandbox-sg", Description="Dev sandbox — all traffic rule"
    )
    ec2.authorize_security_group_ingress(
        GroupId=resp2["GroupId"],
        IpPermissions=[
            {
                "IpProtocol": "-1",
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )

    # ── IAM ───────────────────────────────────────────────────────────────
    # User 1: has console access, no MFA
    iam.create_user(UserName="alice")
    iam.create_login_profile(
        UserName="alice", Password="Temp1234!", PasswordResetRequired=True
    )

    # User 2: console + MFA — should be clean
    iam.create_user(UserName="bob")
    iam.create_login_profile(UserName="bob", Password="Temp1234!", PasswordResetRequired=False)
    serial = iam.create_virtual_mfa_device(VirtualMFADeviceName="bob-mfa")[
        "VirtualMFADevice"
    ]["SerialNumber"]
    iam.enable_mfa_device(
        UserName="bob",
        SerialNumber=serial,
        AuthenticationCode1="123456",
        AuthenticationCode2="789012",
    )

    # User 3: programmatic only — no console access, no MFA needed
    iam.create_user(UserName="ci-runner")
    iam.create_access_key(UserName="ci-runner")

    # No password policy set → IAM_003 fires


def seed_sns(session):
    sns = session.client("sns", region_name=REGION)
    resp = sns.create_topic(Name="cloudshield-alerts-test")
    arn  = resp["TopicArn"]
    os.environ["SNS_TOPIC_ARN"] = arn
    return arn


def main():
    with mock_aws():
        session = boto3.Session(region_name=REGION)

        print(DIVIDER)
        print("  CloudShield-Auditor — local end-to-end run")
        print(DIVIDER)

        print("\n[setup] Seeding violations into fake AWS environment...")
        seed_violations(session)
        sns_arn = seed_sns(session)
        print(f"[setup] SNS topic: {sns_arn}")
        print("[setup] Resources created — firing Lambda handler\n")
        print(DIVIDER)
        print("  STRUCTURED LOGS  (as they appear in CloudWatch)")
        print(DIVIDER)

        # Import here so the env vars above are already set
        from src.handler import lambda_handler

        result = lambda_handler({}, context=None)

        print(DIVIDER)
        print("  HANDLER RETURN VALUE")
        print(DIVIDER)
        print(json.dumps(result, indent=2))

        print(DIVIDER)
        violations = result.get("violations", [])
        print(f"\n  Summary: {result['resources_audited']} resources audited, "
              f"{len(violations)} violation(s) found "
              f"in {result['duration_ms']}ms\n")

        if violations:
            print("  Violations by severity:")
            for sev in ("CRITICAL", "HIGH", "MEDIUM"):
                group = [v for v in violations if v["severity"] == sev]
                if group:
                    print(f"\n  [{sev}]")
                    for v in group:
                        print(f"    {v['rule_id']}  {v['resource_type']}  "
                              f"{v['resource_id']}")
                        print(f"           {v['reason']}")

        print()


if __name__ == "__main__":
    main()
