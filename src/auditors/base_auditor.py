from abc import ABC, abstractmethod
from typing import Any

import structlog

log = structlog.get_logger()


class BaseAuditor(ABC):
    """Abstract base class that all cloud service auditors must implement."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self._account_id: str | None = None

    @abstractmethod
    def fetch_resources(self) -> list[dict[str, Any]]:
        """Retrieve the current live state of all resources for this service."""
        ...

    @abstractmethod
    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Compare fetched resources against policy rules.

        Returns a list of violation dicts, each containing:
          - rule_id, rule_name, severity, resource_id, resource_type, reason
        """
        ...

    def audit(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resources = self.fetch_resources()
        return self.evaluate(resources, rules)

    # ── Helpers for account-level (non-resource) checks ──────────────────────

    @property
    def region(self) -> str:
        return str(getattr(self.session, "region_name", None) or "us-east-1")

    @property
    def account_id(self) -> str:
        """Account the session belongs to, via STS. Cached per auditor instance."""
        if self._account_id is None:
            try:
                ident = self.session.client("sts").get_caller_identity()
                self._account_id = str(ident["Account"])
            except Exception as exc:  # noqa: BLE001
                log.warning("auditor.caller_identity_failed", error=str(exc))
                self._account_id = "unknown"
        return self._account_id

    def account_resource_id(self, setting: str) -> str:
        """Stable, globally unique resource id for an account/region-level setting."""
        return f"{self.account_id}:{self.region}:{setting}"

    @staticmethod
    def build_violation(
        rule: dict[str, Any],
        resource_type: str,
        resource_id: str,
        reason: str,
        tags: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        tags = tags or {}
        return {
            "rule_id":       rule["id"],
            "rule_name":     rule["name"],
            "severity":      rule["severity"],
            "resource_type": resource_type,
            "resource_id":   resource_id,
            "reason":        reason,
            "team":          tags.get("team", "untagged"),
            "owner":         tags.get("owner"),
        }
