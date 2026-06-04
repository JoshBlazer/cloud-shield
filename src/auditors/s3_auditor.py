import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import structlog
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()


class S3Auditor(BaseAuditor):
    """Audits S3 buckets for public access, encryption, versioning, and policy posture."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("s3")

    def fetch_resources(self) -> list[dict[str, Any]]:
        try:
            buckets = self._client.list_buckets().get("Buckets", [])
        except ClientError as exc:
            log.error("s3.list_buckets failed", error=str(exc))
            return []

        def _fetch_one(bucket: dict[str, Any]) -> dict[str, Any]:
            name = bucket["Name"]
            tags = self._get_tags(name)
            return {
                "name":                  name,
                "public_access_block":   self._get_public_access_block(name),
                "encryption":            self._get_encryption(name),
                "versioning":            self._get_versioning(name),
                "bucket_policy_public":  self._is_bucket_policy_public(name),
                "team":                  tags.get("team", "untagged"),
                "owner":                 tags.get("owner"),
            }

        results: list[dict[str, Any]] = []
        # Parallel per-bucket API calls — eliminates N×4 sequential round-trips
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(_fetch_one, b): b for b in buckets}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    log.warning("s3.fetch_bucket_failed", error=str(exc))
        return results

    def _get_public_access_block(self, bucket_name: str) -> dict[str, bool]:
        try:
            resp = self._client.get_public_access_block(Bucket=bucket_name)
            pab: dict[str, bool] = resp["PublicAccessBlockConfiguration"]
            return pab
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchPublicAccessBlockConfiguration":
                return {}
            log.warning("s3.get_public_access_block failed", bucket=bucket_name, error=str(exc))
            return {}

    def _get_encryption(self, bucket_name: str) -> dict[str, Any]:
        try:
            resp = self._client.get_bucket_encryption(Bucket=bucket_name)
            enc: dict[str, Any] = resp.get("ServerSideEncryptionConfiguration", {})
            return enc
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ServerSideEncryptionConfigurationNotFoundError":
                return {}
            log.warning("s3.get_bucket_encryption failed", bucket=bucket_name, error=str(exc))
            return {}

    def _get_versioning(self, bucket_name: str) -> str:
        try:
            resp = self._client.get_bucket_versioning(Bucket=bucket_name)
            status: str = resp.get("Status", "Disabled")
            return status
        except ClientError as exc:
            log.warning("s3.get_bucket_versioning failed", bucket=bucket_name, error=str(exc))
            return "Disabled"

    def _get_tags(self, bucket_name: str) -> dict[str, str]:
        try:
            resp = self._client.get_bucket_tagging(Bucket=bucket_name)
            return {tag["Key"]: tag["Value"] for tag in resp.get("TagSet", [])}
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchTagSet", "NoSuchBucket"):
                return {}
            log.warning("s3.get_bucket_tagging failed", bucket=bucket_name, error=str(exc))
            return {}

    def _is_bucket_policy_public(self, bucket_name: str) -> bool:
        """Return True if the bucket policy explicitly grants access to Principal '*'."""
        try:
            resp   = self._client.get_bucket_policy(Bucket=bucket_name)
            policy = json.loads(resp.get("Policy", "{}"))
            for stmt in policy.get("Statement", []):
                if stmt.get("Effect") != "Allow":
                    continue
                principal = stmt.get("Principal", "")
                # Principal: "*" (anonymous) or Principal: {"AWS": "*"}
                if principal == "*":
                    return True
                if isinstance(principal, dict):
                    aws = principal.get("AWS", [])
                    targets = [aws] if isinstance(aws, str) else aws
                    if "*" in targets:
                        return True
            return False
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchBucketPolicy", "NoSuchBucket"):
                return False
            log.warning("s3.get_bucket_policy failed", bucket=bucket_name, error=str(exc))
            return False

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        for bucket in resources:
            name = bucket["name"]
            tags = {"team": bucket.get("team", "untagged"), "owner": bucket.get("owner")}

            for rule in rules:
                check = rule.get("check")

                if check == "public_access_block_disabled":
                    pab = bucket.get("public_access_block", {})
                    all_blocked = (
                        pab.get("BlockPublicAcls", False)
                        and pab.get("IgnorePublicAcls", False)
                        and pab.get("BlockPublicPolicy", False)
                        and pab.get("RestrictPublicBuckets", False)
                    )
                    if not all_blocked:
                        violations.append(
                            self._build_violation(rule, name, "Public access block is not fully enabled", tags)
                        )

                elif check == "bucket_policy_public":
                    if bucket.get("bucket_policy_public"):
                        violations.append(
                            self._build_violation(rule, name, "Bucket policy grants anonymous (public) access", tags)
                        )

                elif check == "encryption_disabled":
                    if not bucket.get("encryption", {}).get("Rules"):
                        violations.append(
                            self._build_violation(rule, name, "Default server-side encryption is not configured", tags)
                        )

                elif check == "versioning_disabled":
                    if bucket.get("versioning") != "Enabled":
                        violations.append(
                            self._build_violation(rule, name, "Versioning is not enabled", tags)
                        )

        return violations

    @staticmethod
    def _build_violation(
        rule: dict[str, Any], resource_id: str, reason: str, tags: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "rule_id":       rule["id"],
            "rule_name":     rule["name"],
            "severity":      rule["severity"],
            "resource_type": "AWS::S3::Bucket",
            "resource_id":   resource_id,
            "reason":        reason,
            "team":          (tags or {}).get("team", "untagged"),
            "owner":         (tags or {}).get("owner"),
        }
