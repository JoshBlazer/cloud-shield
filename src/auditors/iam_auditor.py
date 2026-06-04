import csv
import io
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

import structlog
from botocore.config import Config
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()

# Adaptive retry mode back-offs automatically under IAM's low rate limits
_RETRY_CFG = Config(retries={"mode": "adaptive"})


class IAMAuditor(BaseAuditor):
    """
    Audits IAM posture using the credential report (single API call) rather than
    per-user fan-out — eliminates N×4 sequential calls and avoids IAM rate throttling.
    User tags are still fetched per-user but in parallel via ThreadPoolExecutor.
    """

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("iam", config=_RETRY_CFG)

    # ── Credential report ─────────────────────────────────────────────────────

    def _get_credential_report(self) -> list[dict[str, str]]:
        """
        Generate + download the IAM credential report.
        Returns the CSV rows as a list of dicts, or [] on timeout.

        AWS may return State=STARTED or INPROGRESS, and get_credential_report()
        raises ReportInProgress until generation is done. Poll by attempting the
        get() directly — this is simpler and works with moto (which returns a
        usable report immediately regardless of the generate() state).
        """
        self._client.generate_credential_report()  # trigger generation (idempotent)
        deadline = _time.time() + 30
        while True:
            try:
                content = self._client.get_credential_report()["Content"].decode("utf-8")
                return list(csv.DictReader(io.StringIO(content)))
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code not in ("ReportInProgress", "ReportNotPresent"):
                    raise
                if _time.time() >= deadline:
                    log.warning("iam.credential_report_timeout")
                    return []
                _time.sleep(2)

    @staticmethod
    def _parse_key_age(rotated_str: str) -> int | None:
        """Return days since the key was last rotated, or None if unavailable."""
        if not rotated_str or rotated_str in ("N/A", "no_information", "not_supported"):
            return None
        try:
            rotated = datetime.fromisoformat(rotated_str.replace("Z", "+00:00"))
            return (datetime.now(tz=UTC) - rotated).days
        except ValueError:
            return None

    def _get_user_tags(self, username: str) -> dict[str, str]:
        try:
            resp = self._client.list_user_tags(UserName=username)
            return {t["Key"]: t["Value"] for t in resp.get("Tags", [])}
        except ClientError as exc:
            log.warning("iam.list_user_tags failed", username=username, error=str(exc))
            return {}

    def _is_root_mfa_active(self) -> bool:
        """Fallback for when the credential report omits the root account row."""
        try:
            return bool(self._client.get_account_summary()
                        .get("SummaryMap", {}).get("AccountMFAEnabled", 0))
        except ClientError as exc:
            log.warning("iam.get_account_summary failed", error=str(exc))
            return True  # assume compliant to avoid false positives

    # ── Resource fetching ─────────────────────────────────────────────────────

    def fetch_resources(self) -> list[dict[str, Any]]:
        report = self._get_credential_report()
        # Don't early-return on empty report — account-level resources are always appended below.
        user_rows = [r for r in report if r.get("user") != "<root_account>"]
        usernames = [r["user"] for r in user_rows]

        # Parallel tag fetches — the only remaining per-user API call
        tags_by_user: dict[str, dict[str, str]] = {}
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(self._get_user_tags, u): u for u in usernames}
            for future in as_completed(futures):
                username = futures[future]
                try:
                    tags_by_user[username] = future.result()
                except Exception as exc:  # noqa: BLE001
                    log.warning("iam.tags_fetch_failed", username=username, error=str(exc))
                    tags_by_user[username] = {}

        resources: list[dict[str, Any]] = []
        root_mfa_active: bool | None = None

        for row in report:
            username = row.get("user", "")

            if username == "<root_account>":
                root_mfa_active = row.get("mfa_active", "false").lower() == "true"
                continue

            keys: list[dict[str, Any]] = []
            for n in ("1", "2"):
                if row.get(f"access_key_{n}_active", "false").lower() == "true":
                    age = self._parse_key_age(row.get(f"access_key_{n}_last_rotated", "N/A"))
                    if age is not None:
                        keys.append({"key_id": f"access-key-{n}", "status": "Active", "age_days": age})

            tags = tags_by_user.get(username, {})
            resources.append({
                "type":               "user",
                "username":           username,
                "has_console_access": row.get("password_enabled", "false").lower() == "true",
                "mfa_devices":        [{"SerialNumber": "mfa"}]
                                      if row.get("mfa_active", "false").lower() == "true"
                                      else [],
                "access_keys":        keys,
                "team":               tags.get("team", "untagged"),
                "owner":              tags.get("owner"),
            })
            log.debug("iam.fetched_user", username=username)

        # Credential report may omit the root account row in some environments
        if root_mfa_active is None:
            root_mfa_active = self._is_root_mfa_active()

        resources.append({"type": "account_summary", "root_mfa_active": root_mfa_active})
        resources.append({"type": "account", "password_policy": self._get_password_policy()})
        return resources

    def _get_password_policy(self) -> dict[str, Any]:
        try:
            policy: dict[str, Any] = self._client.get_account_password_policy().get("PasswordPolicy", {})
            return policy
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchEntity":
                return {}
            log.warning("iam.get_account_password_policy failed", error=str(exc))
            return {}

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        users        = [r for r in resources if r.get("type") == "user"]
        account      = next((r for r in resources if r.get("type") == "account"), {})
        acct_summary = next((r for r in resources if r.get("type") == "account_summary"), {})

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
                                    f"Key '{key['key_id']}' for '{user['username']}' is "
                                    f"{key['age_days']} days old (max {max_age})",
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
            reasons.append(f"Min length is {policy.get('MinimumPasswordLength', 0)}, required {min_len}")

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
            reasons.append(f"Reuse prevention is {policy.get('PasswordReusePrevention', 0)}, required {min_reuse}")

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
