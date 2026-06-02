from abc import ABC, abstractmethod
from typing import Any


class BaseAuditor(ABC):
    """Abstract base class that all cloud service auditors must implement."""

    def __init__(self, session: Any) -> None:
        self.session = session

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
