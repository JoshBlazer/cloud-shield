from datetime import UTC, datetime
from typing import Any

import structlog
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()


class IAMAuditor(BaseAuditor):
    """Audits IAM users, access keys, password policy, and root account MFA."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("iam")

    def fetch_resources(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []

        try:
            paginator = self._client.get_paginator("list_users")
            for page in paginator.paginate():
                for user in page.get("Users", []):
                    username  = user["UserName"]
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
        resources.append({"type": "account_summary", "root_mfa_active": self._is_root_mfa_active()})
        return resources

    # ── Per-user helpers ──────────────────────────────────────────────────────

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
            now  = datetime.now(tz=UTC)
            for meta in resp.get("AccessKeyMetadata", []):
                created_at = meta["CreateDate"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                keys.append(
                    {
                        "key_id":   meta["AccessKeyId"],
                        "status":   meta["Status"],
                        "age_days": (now - created_at).days,
                    }
                )
        except ClientError as exc:
            log.warning("iam.list_access_keys failed", username=username, error=str(exc))
        return keys

    # ── Account-level helpers ─────────────────────────────────────────────────

    def _get_password_policy(self) -> dict[str, Any]:
        try:
            return self._client.get_account_password_policy().get("PasswordPolicy", {})
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchEntity":
                return {}
            log.warning("iam.get_account_password_policy failed", error=str(exc))
            return {}

    def _is_root_mfa_active(self) -> bool:
        """AccountMFAEnabled = 1 means the root account has at least one MFA device."""
        try:
            resp = self._client.get_account_summary()
            return bool(resp.get("SummaryMap", {}).get("AccountMFAEnabled", 0))
        except ClientError as exc:
            log.warning("iam.get_account_summary failed", error=str(exc))
            return True  # assume compliant on error to avoid false positive

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        users          = [r for r in resources if r.get("type") == "user"]
        account        = next((r for r in resources if r.get("type") == "account"), {})
        acct_summary   = next((r for r in resources if r.get("type") == "account_summary"), {})

        for rule in rules:
            check = rule.get("check")

            if check == "mfa_not_enabled":
                for user in users:
                    if user["has_console_access"] and not user["mfa_devices"]:
                        tags = {"team": user.get("team", "untagged"), "owner": user.get("owner")}
                        violations.append(
                            self._build_violation(
                                rule, user["username"], "AWS::IAM::User",
                                f"User '{user['username']}' has console access but no MFA device",
                                tags,
                            )
                        )

            elif check == "access_key_not_rotated":
                max_age = rule.get("max_age_days", 90)
                for user in users:
                    tags = {"team": user.get("team", "untagged"), "owner": user.get("owner")}
                    for key in user.get("access_keys", []):
                        if key["status"] == "Active" and key["age_days"] > max_age:
                            violations.append(
                                self._build_violation(
                                    rule,
                                    f"{user['username']}/{key['key_id']}",
                                    "AWS::IAM::AccessKey",
                                    f"Key '{key['key_id']}' for '{user['username']}' is {key['age_days']} days old (max {max_age})",
                                    tags,
                                )
                            )

            elif check == "weak_password_policy":
                policy  = account.get("password_policy", {})
                reasons = self._audit_password_policy(rule, policy)
                if reasons:
                    violations.append(
                        self._build_violation(
                            rule, "account-password-policy", "AWS::IAM::PasswordPolicy",
                            "; ".join(reasons),
                        )
                    )

            elif check == "root_mfa_disabled":
                if not acct_summary.get("root_mfa_active", True):
                    violations.append(
                        self._build_violation(
                            rule, "root", "AWS::IAM::RootAccount",
                            "Root account does not have MFA enabled",
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
        for flag, key in [
            ("require_uppercase", "RequireUppercaseCharacters"),
            ("require_lowercase", "RequireLowercaseCharacters"),
            ("require_numbers",   "RequireNumbers"),
            ("require_symbols",   "RequireSymbols"),
        ]:
            if rule.get(flag) and not policy.get(key, False):
                reasons.append(f"{key.replace('Require', '')} not required")

        max_age    = rule.get("max_age_days")
        policy_age = policy.get("MaxPasswordAge")
        if max_age is not None and (not policy_age or policy_age > max_age):
            reasons.append(f"Password max age is {policy_age or 'not set'}, required <= {max_age} days")

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
