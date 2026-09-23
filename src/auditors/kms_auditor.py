from typing import Any

import structlog
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()

_RESOURCE_TYPE = "AWS::KMS::Key"


class KMSAuditor(BaseAuditor):
    """Audits customer-managed KMS keys for automatic key rotation."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("kms")

    def fetch_resources(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            paginator = self._client.get_paginator("list_keys")
            key_ids = [k["KeyId"] for page in paginator.paginate() for k in page.get("Keys", [])]
        except ClientError as exc:
            self.record_error("kms:ListKeys", exc)
            return resources

        for key_id in key_ids:
            try:
                meta = self._client.describe_key(KeyId=key_id)["KeyMetadata"]
            except ClientError as exc:
                self.record_error("kms:DescribeKey", exc, key_id=key_id)
                continue

            # Only enabled, customer-managed, symmetric encryption keys support
            # automatic rotation; AWS-managed keys rotate on AWS's own schedule.
            if (
                meta.get("KeyManager") != "CUSTOMER"
                or meta.get("KeyState") != "Enabled"
                or meta.get("KeySpec", "SYMMETRIC_DEFAULT") != "SYMMETRIC_DEFAULT"
                or meta.get("Origin", "AWS_KMS") != "AWS_KMS"
            ):
                continue

            try:
                rotation = self._client.get_key_rotation_status(KeyId=key_id)
                meta["KeyRotationEnabled"] = bool(rotation.get("KeyRotationEnabled"))
            except ClientError as exc:
                self.record_error("kms:GetKeyRotationStatus", exc, key_id=key_id)
                continue

            try:
                tag_resp = self._client.list_resource_tags(KeyId=key_id)
                meta["Tags"] = {t["TagKey"]: t["TagValue"] for t in tag_resp.get("Tags", [])}
            except ClientError:
                meta["Tags"] = {}

            resources.append(meta)
        return resources

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        for key in resources:
            for rule in rules:
                if rule.get("check") == "kms_rotation_disabled" and not key.get("KeyRotationEnabled"):
                    violations.append(self.build_violation(
                        rule, _RESOURCE_TYPE, key.get("Arn", key["KeyId"]),
                        f"KMS key '{key['KeyId']}' does not have automatic rotation enabled",
                        key.get("Tags"),
                    ))

        return violations
