"""Integration tests: spins up a fake AWS env, creates misconfigured resources,
and verifies the auditors catch every violation."""


from src.auditors.ec2_auditor import EC2Auditor
from src.auditors.iam_auditor import IAMAuditor
from src.auditors.s3_auditor import S3Auditor

# ---------------------------------------------------------------------------
# S3 tests
# ---------------------------------------------------------------------------


class TestS3Auditor:
    def _create_bucket(self, session, name: str) -> None:
        s3 = session.client("s3")
        s3.create_bucket(Bucket=name)

    def _enable_public_access_block(self, session, name: str) -> None:
        s3 = session.client("s3")
        s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )

    def _enable_encryption(self, session, name: str) -> None:
        s3 = session.client("s3")
        s3.put_bucket_encryption(
            Bucket=name,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256"
                        }
                    }
                ]
            },
        )

    def _enable_versioning(self, session, name: str) -> None:
        s3 = session.client("s3")
        s3.put_bucket_versioning(
            Bucket=name,
            VersioningConfiguration={"Status": "Enabled"},
        )

    def test_detects_missing_public_access_block(self, mock_s3_session, s3_rules):
        self._create_bucket(mock_s3_session, "unprotected-bucket")
        auditor = S3Auditor(mock_s3_session)
        violations = auditor.audit(s3_rules)

        rule_ids = {v["rule_id"] for v in violations}
        assert "S3_001" in rule_ids

    def test_detects_missing_encryption(self, mock_s3_session, s3_rules):
        self._create_bucket(mock_s3_session, "unencrypted-bucket")
        auditor = S3Auditor(mock_s3_session)
        violations = auditor.audit(s3_rules)

        rule_ids = {v["rule_id"] for v in violations}
        assert "S3_002" in rule_ids

    def test_detects_versioning_disabled(self, mock_s3_session, s3_rules):
        self._create_bucket(mock_s3_session, "no-versioning-bucket")
        auditor = S3Auditor(mock_s3_session)
        violations = auditor.audit(s3_rules)

        rule_ids = {v["rule_id"] for v in violations}
        assert "S3_003" in rule_ids

    def test_compliant_bucket_has_no_violations(self, mock_s3_session, s3_rules):
        name = "compliant-bucket"
        self._create_bucket(mock_s3_session, name)
        self._enable_public_access_block(mock_s3_session, name)
        self._enable_encryption(mock_s3_session, name)
        self._enable_versioning(mock_s3_session, name)

        auditor = S3Auditor(mock_s3_session)
        violations = auditor.audit(s3_rules)

        assert violations == []

    def test_violation_structure(self, mock_s3_session, s3_rules):
        self._create_bucket(mock_s3_session, "check-structure")
        auditor = S3Auditor(mock_s3_session)
        violations = auditor.audit(s3_rules)

        assert violations, "expected at least one violation"
        v = violations[0]
        assert "rule_id" in v
        assert "severity" in v
        assert "resource_id" in v
        assert "resource_type" in v
        assert "reason" in v
        assert v["resource_type"] == "AWS::S3::Bucket"

    def test_empty_account_returns_no_violations(self, mock_s3_session, s3_rules):
        auditor = S3Auditor(mock_s3_session)
        violations = auditor.audit(s3_rules)
        assert violations == []

    def test_detects_public_bucket_policy(self, mock_s3_session, s3_rules):
        """S3_004 must fire when a bucket policy grants Principal: '*'."""
        import json
        s3 = mock_s3_session.client("s3")
        s3.create_bucket(Bucket="policy-public-bucket")
        s3.put_bucket_policy(
            Bucket="policy-public-bucket",
            Policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": "arn:aws:s3:::policy-public-bucket/*",
                }],
            }),
        )
        auditor = S3Auditor(mock_s3_session)
        violations = auditor.audit(s3_rules)
        assert "S3_004" in {v["rule_id"] for v in violations}

    def test_private_bucket_policy_no_s3_004(self, mock_s3_session, s3_rules):
        """S3_004 must not fire when the bucket policy restricts to a specific principal."""
        import json
        s3 = mock_s3_session.client("s3")
        s3.create_bucket(Bucket="policy-private-bucket")
        s3.put_bucket_policy(
            Bucket="policy-private-bucket",
            Policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
                    "Action": "s3:GetObject",
                    "Resource": "arn:aws:s3:::policy-private-bucket/*",
                }],
            }),
        )
        auditor = S3Auditor(mock_s3_session)
        violations = auditor.audit(s3_rules)
        assert "S3_004" not in {v["rule_id"] for v in violations}


# ---------------------------------------------------------------------------
# EC2 / Security Group tests
# ---------------------------------------------------------------------------


class TestEC2Auditor:
    def _create_sg(self, session, name: str, description: str = "test") -> str:
        ec2 = session.client("ec2")
        resp = ec2.create_security_group(GroupName=name, Description=description)
        return resp["GroupId"]

    def _add_ingress(self, session, sg_id: str, port: int, cidr: str = "0.0.0.0/0") -> None:
        ec2 = session.client("ec2")
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": port,
                    "ToPort": port,
                    "IpRanges": [{"CidrIp": cidr}],
                }
            ],
        )

    def _add_all_traffic_ingress(self, session, sg_id: str) -> None:
        ec2 = session.client("ec2")
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    "IpProtocol": "-1",
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                }
            ],
        )

    def test_detects_open_ssh(self, mock_ec2_session, ec2_rules):
        sg_id = self._create_sg(mock_ec2_session, "open-ssh-sg")
        self._add_ingress(mock_ec2_session, sg_id, 22)

        auditor = EC2Auditor(mock_ec2_session)
        violations = auditor.audit(ec2_rules)

        rule_ids = {v["rule_id"] for v in violations}
        assert "EC2_001" in rule_ids

    def test_detects_open_rdp(self, mock_ec2_session, ec2_rules):
        sg_id = self._create_sg(mock_ec2_session, "open-rdp-sg")
        self._add_ingress(mock_ec2_session, sg_id, 3389)

        auditor = EC2Auditor(mock_ec2_session)
        violations = auditor.audit(ec2_rules)

        rule_ids = {v["rule_id"] for v in violations}
        assert "EC2_002" in rule_ids

    def test_detects_all_traffic_rule(self, mock_ec2_session, ec2_rules):
        sg_id = self._create_sg(mock_ec2_session, "all-traffic-sg")
        self._add_all_traffic_ingress(mock_ec2_session, sg_id)

        auditor = EC2Auditor(mock_ec2_session)
        violations = auditor.audit(ec2_rules)

        rule_ids = {v["rule_id"] for v in violations}
        assert "EC2_003" in rule_ids

    def test_restricted_sg_has_no_violations(self, mock_ec2_session, ec2_rules):
        sg_id = self._create_sg(mock_ec2_session, "restricted-sg")
        # Allow SSH only from a specific corp CIDR — not the open world
        self._add_ingress(mock_ec2_session, sg_id, 22, cidr="10.0.0.0/8")

        auditor = EC2Auditor(mock_ec2_session)
        violations = auditor.audit(ec2_rules)

        assert violations == []

    def test_violation_structure(self, mock_ec2_session, ec2_rules):
        sg_id = self._create_sg(mock_ec2_session, "structure-check-sg")
        self._add_ingress(mock_ec2_session, sg_id, 22)

        auditor = EC2Auditor(mock_ec2_session)
        violations = auditor.audit(ec2_rules)

        assert violations
        v = violations[0]
        assert "rule_id" in v
        assert "severity" in v
        assert "resource_id" in v
        assert v["resource_type"] == "AWS::EC2::SecurityGroup"

    def test_default_sg_without_custom_rules_has_no_violations(self, mock_ec2_session, ec2_rules):
        # Moto creates a default VPC and default SG; verify the default SG doesn't
        # trigger false positives for rules we haven't explicitly violated.
        auditor = EC2Auditor(mock_ec2_session)
        resources = auditor.fetch_resources()
        # Default SG has no custom ingress additions from our test code
        violations = auditor.evaluate(resources, ec2_rules)
        # The default SG has a self-referencing rule but no 0.0.0.0/0 ingress
        assert violations == []


# ---------------------------------------------------------------------------
# IAM tests
# ---------------------------------------------------------------------------


class TestIAMAuditor:
    def _create_console_user(self, session, username: str) -> None:
        iam = session.client("iam")
        iam.create_user(UserName=username)
        iam.create_login_profile(UserName=username, Password="Test1234!", PasswordResetRequired=False)

    def _enable_mfa(self, session, username: str) -> None:
        iam = session.client("iam")
        serial = iam.create_virtual_mfa_device(VirtualMFADeviceName=f"{username}-mfa")[
            "VirtualMFADevice"
        ]["SerialNumber"]
        iam.enable_mfa_device(
            UserName=username,
            SerialNumber=serial,
            AuthenticationCode1="123456",
            AuthenticationCode2="789012",
        )

    def _strong_password_policy(self, session) -> None:
        session.client("iam").update_account_password_policy(
            MinimumPasswordLength=16,
            RequireUppercaseCharacters=True,
            RequireLowercaseCharacters=True,
            RequireNumbers=True,
            RequireSymbols=True,
            MaxPasswordAge=90,
            PasswordReusePrevention=12,
        )

    # --- MFA ---

    def test_detects_console_user_without_mfa(self, mock_iam_session, iam_rules):
        self._create_console_user(mock_iam_session, "alice")
        auditor = IAMAuditor(mock_iam_session)
        violations = auditor.audit(iam_rules)
        assert any(v["rule_id"] == "IAM_001" for v in violations)

    def test_no_mfa_violation_when_mfa_enabled(self, mock_iam_session, iam_rules):
        self._create_console_user(mock_iam_session, "bob")
        self._enable_mfa(mock_iam_session, "bob")
        auditor = IAMAuditor(mock_iam_session)
        violations = auditor.audit(iam_rules)
        assert not any(v["rule_id"] == "IAM_001" for v in violations)

    def test_no_mfa_violation_for_service_account(self, mock_iam_session, iam_rules):
        # Programmatic-only users have no login profile so MFA doesn't apply
        mock_iam_session.client("iam").create_user(UserName="ci-deploy")
        auditor = IAMAuditor(mock_iam_session)
        violations = auditor.audit(iam_rules)
        assert not any(v["rule_id"] == "IAM_001" for v in violations)

    def test_mfa_violation_structure(self, mock_iam_session, iam_rules):
        self._create_console_user(mock_iam_session, "carol")
        auditor = IAMAuditor(mock_iam_session)
        violations = [v for v in auditor.audit(iam_rules) if v["rule_id"] == "IAM_001"]
        assert violations
        v = violations[0]
        assert v["resource_type"] == "AWS::IAM::User"
        assert v["resource_id"] == "carol"
        assert "severity" in v and "reason" in v

    # --- Access key rotation ---

    def test_detects_old_access_key(self, mock_iam_session, iam_rules):
        # Bypass fetch_resources — Moto always creates keys with today's date.
        # Craft a resource dict directly to test evaluate() in isolation.
        auditor = IAMAuditor(mock_iam_session)
        resources = [
            {
                "type": "user",
                "username": "dave",
                "has_console_access": False,
                "mfa_devices": [],
                "access_keys": [
                    {"key_id": "AKIAIOSFODNN7EXAMPLE", "status": "Active", "age_days": 120}
                ],
            },
            {"type": "account", "password_policy": {}},
        ]
        rotation_rule = next(r for r in iam_rules if r["id"] == "IAM_002")
        violations = auditor.evaluate(resources, [rotation_rule])
        assert any(v["rule_id"] == "IAM_002" for v in violations)

    def test_no_violation_for_fresh_access_key(self, mock_iam_session, iam_rules):
        iam = mock_iam_session.client("iam")
        iam.create_user(UserName="eve")
        iam.create_access_key(UserName="eve")
        auditor = IAMAuditor(mock_iam_session)
        violations = auditor.audit(iam_rules)
        assert not any(v["rule_id"] == "IAM_002" for v in violations)

    def test_inactive_old_key_not_flagged(self, mock_iam_session, iam_rules):
        # Inactive keys don't need rotation — only Active ones do
        auditor = IAMAuditor(mock_iam_session)
        resources = [
            {
                "type": "user",
                "username": "frank",
                "has_console_access": False,
                "mfa_devices": [],
                "access_keys": [
                    {"key_id": "AKIAIOSFODNN7EXAMPLE", "status": "Inactive", "age_days": 200}
                ],
            },
            {"type": "account", "password_policy": {}},
        ]
        rotation_rule = next(r for r in iam_rules if r["id"] == "IAM_002")
        violations = auditor.evaluate(resources, [rotation_rule])
        assert not any(v["rule_id"] == "IAM_002" for v in violations)

    # --- Password policy ---

    def test_detects_missing_password_policy(self, mock_iam_session, iam_rules):
        auditor = IAMAuditor(mock_iam_session)
        violations = auditor.audit(iam_rules)
        assert any(v["rule_id"] == "IAM_003" for v in violations)

    def test_detects_weak_password_policy(self, mock_iam_session, iam_rules):
        mock_iam_session.client("iam").update_account_password_policy(MinimumPasswordLength=6)
        auditor = IAMAuditor(mock_iam_session)
        violations = auditor.audit(iam_rules)
        assert any(v["rule_id"] == "IAM_003" for v in violations)

    def test_no_violation_for_strong_password_policy(self, mock_iam_session, iam_rules):
        self._strong_password_policy(mock_iam_session)
        auditor = IAMAuditor(mock_iam_session)
        violations = auditor.audit(iam_rules)
        assert not any(v["rule_id"] == "IAM_003" for v in violations)

    def test_password_policy_violation_structure(self, mock_iam_session, iam_rules):
        auditor = IAMAuditor(mock_iam_session)
        violations = [v for v in auditor.audit(iam_rules) if v["rule_id"] == "IAM_003"]
        assert violations
        v = violations[0]
        assert v["resource_type"] == "AWS::IAM::PasswordPolicy"
        assert v["resource_id"] == "account-password-policy"

    # --- Root MFA (IAM_004) ---

    def test_detects_root_mfa_disabled(self, mock_iam_session):
        """evaluate() must flag IAM_004 when root_mfa_active is False."""
        auditor = IAMAuditor(mock_iam_session)
        resources = [
            {"type": "account_summary", "root_mfa_active": False},
            {"type": "account", "password_policy": {}},
        ]
        root_mfa_rule = {
            "id": "IAM_004", "name": "Root Account MFA Not Enabled",
            "severity": "CRITICAL", "check": "root_mfa_disabled",
        }
        violations = auditor.evaluate(resources, [root_mfa_rule])
        assert any(v["rule_id"] == "IAM_004" for v in violations)
        v = next(v for v in violations if v["rule_id"] == "IAM_004")
        assert v["resource_type"] == "AWS::IAM::RootAccount"
        assert v["resource_id"] == "root"

    def test_root_mfa_enabled_no_violation(self, mock_iam_session):
        """evaluate() must not flag IAM_004 when root MFA is active."""
        auditor = IAMAuditor(mock_iam_session)
        resources = [
            {"type": "account_summary", "root_mfa_active": True},
            {"type": "account", "password_policy": {}},
        ]
        root_mfa_rule = {
            "id": "IAM_004", "name": "Root Account MFA Not Enabled",
            "severity": "CRITICAL", "check": "root_mfa_disabled",
        }
        violations = auditor.evaluate(resources, [root_mfa_rule])
        assert not any(v["rule_id"] == "IAM_004" for v in violations)
