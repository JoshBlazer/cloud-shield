from datetime import UTC, datetime
from typing import Any

import structlog
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()


class IAMAuditor(BaseAuditor):
    """Audits IAM users for MFA enforcement, access key rotation, and password policy."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("iam")

    def fetch_resources(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []

        try:
            paginator = self._client.get_paginator("list_users")
            for page in paginator.paginate():
                for user in page.get("Users", []):
                    username = user["UserName"]
                    user_tags = self._get_user_tags(username)
                    resources.append(
                        {
                            "type":               "user",
                            "username":           username,
                            "has_console_access": self._has_console_access(username),
                            "mfa_devices":        self._get_mfa_devices(username),
                            "access_keys":        self._get_access_keys(username),
                            "team":               user_tags.get("team", "untagged"),
                            "owner":              user_tags.get("owner"),
                        }
                    )
                    log.debug("iam.fetched_user", username=username)
        except ClientError as exc:
            log.error("iam.list_users failed", error=str(exc))

        resources.append({"type": "account", "password_policy": self._get_password_policy()})
        return resources

    def _get_user_tags(self, username: str) -> dict[str, str]:
        try:
            resp = self._client.list_user_tags(UserName=username)
            return {tag["Key"]: tag["Value"] for tag in resp.get("Tags", [])}
        except ClientError as exc:
            log.warning("iam.list_user_tags failed", username=username, error=str(exc))
            return {}

    def _has_console_access(self, username: str) -> bool:
        try:
            self._client.get_login_profile(UserName=username)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchEntity":
                return False
            log.warning("iam.get_login_profile failed", username=username, error=str(exc))
            return False

    def _get_mfa_devices(self, username: str) -> list[dict[str, Any]]:
        try:
            return self._client.list_mfa_devices(UserName=username).get("MFADevices", [])
        except ClientError as exc:
            log.warning("iam.list_mfa_devices failed", username=username, error=str(exc))
            return []

    def _get_access_keys(self, username: str) -> list[dict[str, Any]]:
        keys: list[dict[str, Any]] = []
        try:
            resp = self._client.list_access_keys(UserName=username)
            now = datetime.now(tz=UTC)
            for meta in resp.get("AccessKeyMetadata", []):
                created_at = meta["CreateDate"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                keys.append(
                    {
                        "key_id": meta["AccessKeyId"],
                        "status": meta["Status"],
                        "age_days": (now - created_at).days,
                    }
                )
        except ClientError as exc:
            log.warning("iam.list_access_keys failed", username=username, error=str(exc))
        return keys

    def _get_password_policy(self) -> dict[str, Any]:
        try:
            return self._client.get_account_password_policy().get("PasswordPolicy", {})
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchEntity":
                return {}
            log.warning("iam.get_account_password_policy failed", error=str(exc))
            return {}

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        users = [r for r in resources if r.get("type") == "user"]
        account = next((r for r in resources if r.get("type") == "account"), {})

        for rule in rules:
            check = rule.get("check")

            if check == "mfa_not_enabled":
                for user in users:
                    if user["has_console_access"] and not user["mfa_devices"]:
                        user_tags = {"team": user.get("team", "untagged"), "owner": user.get("owner")}
                        violations.append(
                            self._build_violation(
                                rule, user["username"], "AWS::IAM::User",
                                f"User '{user['username']}' has console access but no MFA device",
                                user_tags,
                            )
                        )

            elif check == "access_key_not_rotated":
                max_age = rule.get("max_age_days", 90)
                for user in users:
                    user_tags = {"team": user.get("team", "untagged"), "owner": user.get("owner")}
                    for key in user.get("access_keys", []):
                        if key["status"] == "Active" and key["age_days"] > max_age:
                            violations.append(
                                self._build_violation(
                                    rule,
                                    f"{user['username']}/{key['key_id']}",
                                    "AWS::IAM::AccessKey",
                                    f"Key '{key['key_id']}' for '{user['username']}' is {key['age_days']} days old (max {max_age})",
                                    user_tags,
                                )
                            )

            elif check == "weak_password_policy":
                policy = account.get("password_policy", {})
                reasons = self._audit_password_policy(rule, policy)
                if reasons:
                    violations.append(
                        self._build_violation(
                            rule, "account-password-policy", "AWS::IAM::PasswordPolicy",
                            "; ".join(reasons),
                        )
                    )

        return violations

    @staticmethod
    def _audit_password_policy(rule: dict[str, Any], policy: dict[str, Any]) -> list[str]:
        if not policy:
            return ["No account password policy is configured"]

        reasons: list[str] = []
        min_len = rule.get("min_length", 14)
        if policy.get("MinimumPasswordLength", 0) < min_len:
            reasons.append(
                f"Min length is {policy.get('MinimumPasswordLength', 0)}, required {min_len}"
            )
        if rule.get("require_uppercase") and not policy.get("RequireUppercaseCharacters", False):
            reasons.append("Uppercase characters not required")
        if rule.get("require_lowercase") and not policy.get("RequireLowercaseCharacters", False):
            reasons.append("Lowercase characters not required")
        if rule.get("require_numbers") and not policy.get("RequireNumbers", False):
            reasons.append("Numbers not required")
        if rule.get("require_symbols") and not policy.get("RequireSymbols", False):
            reasons.append("Symbols not required")

        max_age = rule.get("max_age_days")
        if max_age is not None:
            policy_age = policy.get("MaxPasswordAge")
            if not policy_age or policy_age > max_age:
                reasons.append(
                    f"Password max age is {policy_age or 'not set'}, required <= {max_age} days"
                )

        min_reuse = rule.get("prevent_reuse", 5)
        if policy.get("PasswordReusePrevention", 0) < min_reuse:
            reasons.append(
                f"Reuse prevention is {policy.get('PasswordReusePrevention', 0)}, required {min_reuse}"
            )

        return reasons

    @staticmethod
    def _build_violation(
        rule: dict[str, Any], resource_id: str, resource_type: str, reason: str,
        tags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "rule_id":       rule["id"],
            "rule_name":     rule["name"],
            "severity":      rule["severity"],
            "resource_type": resource_type,
            "resource_id":   resource_id,
            "reason":        reason,
            "team":          (tags or {}).get("team", "untagged"),
            "owner":         (tags or {}).get("owner"),
        }
