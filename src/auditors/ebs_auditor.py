from typing import Any

import structlog
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()

_VOLUME_TYPE   = "AWS::EC2::Volume"
_SNAPSHOT_TYPE = "AWS::EC2::Snapshot"
_ACCOUNT_TYPE  = "AWS::::Account"


class EBSAuditor(BaseAuditor):
    """Audits EBS volumes, snapshots, and the region's encryption-by-default setting."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("ec2")

    def fetch_resources(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []

        try:
            enabled = self._client.get_ebs_encryption_by_default().get("EbsEncryptionByDefault")
            resources.append({"_kind": "account", "EbsEncryptionByDefault": bool(enabled)})
        except ClientError as exc:
            log.error("ebs.get_ebs_encryption_by_default failed", error=str(exc))

        try:
            for page in self._client.get_paginator("describe_volumes").paginate():
                for vol in page.get("Volumes", []):
                    resources.append({"_kind": "volume", **vol})
        except ClientError as exc:
            log.error("ebs.describe_volumes failed", error=str(exc))

        try:
            pages = self._client.get_paginator("describe_snapshots").paginate(OwnerIds=["self"])
            for page in pages:
                for snap in page.get("Snapshots", []):
                    snap["IsPublic"] = self._snapshot_is_public(snap["SnapshotId"])
                    resources.append({"_kind": "snapshot", **snap})
        except ClientError as exc:
            log.error("ebs.describe_snapshots failed", error=str(exc))

        return resources

    def _snapshot_is_public(self, snapshot_id: str) -> bool:
        try:
            attr = self._client.describe_snapshot_attribute(
                SnapshotId=snapshot_id, Attribute="createVolumePermission"
            )
        except ClientError as exc:
            log.warning("ebs.describe_snapshot_attribute failed", snapshot=snapshot_id, error=str(exc))
            return False
        return any(p.get("Group") == "all" for p in attr.get("CreateVolumePermissions", []))

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        for res in resources:
            kind = res["_kind"]
            tags = {t["Key"]: t["Value"] for t in res.get("Tags", [])}

            for rule in rules:
                check = rule.get("check")

                if check == "ebs_default_encryption_disabled" and kind == "account":
                    if not res["EbsEncryptionByDefault"]:
                        violations.append(self.build_violation(
                            rule, _ACCOUNT_TYPE, self.account_resource_id("ebs-encryption-by-default"),
                            f"EBS encryption by default is disabled in {self.region}",
                        ))

                elif check == "ebs_volume_unencrypted" and kind == "volume":
                    if not res.get("Encrypted"):
                        violations.append(self.build_violation(
                            rule, _VOLUME_TYPE, res["VolumeId"],
                            f"EBS volume '{res['VolumeId']}' is not encrypted",
                            tags,
                        ))

                elif check == "ebs_snapshot_public" and kind == "snapshot":
                    if res.get("IsPublic"):
                        violations.append(self.build_violation(
                            rule, _SNAPSHOT_TYPE, res["SnapshotId"],
                            f"EBS snapshot '{res['SnapshotId']}' is shared publicly",
                            tags,
                        ))

        return violations
