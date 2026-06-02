from pathlib import Path
from typing import Any, TypedDict

import boto3
import structlog
import yaml

from src.auditors.ec2_auditor import EC2Auditor
from src.auditors.iam_auditor import IAMAuditor
from src.auditors.s3_auditor import S3Auditor

log = structlog.get_logger()

_POLICY_PATH = Path(__file__).parent.parent.parent / "policies.yaml"

_AUDITOR_MAP = {
    "s3": S3Auditor,
    "ec2": EC2Auditor,
    "iam": IAMAuditor,
}


class AuditResult(TypedDict):
    violations: list[dict[str, Any]]
    resources_audited: int


def _load_policies(path: Path = _POLICY_PATH) -> dict[str, Any]:
    with open(path) as fh:
        return yaml.safe_load(fh)


def run_audit(session: Any = None) -> AuditResult:
    """
    Load policies, instantiate auditors, and collect all violations.

    Calls fetch_resources() and evaluate() separately so the evaluator can
    count total resources audited without a second round-trip to the cloud.
    """
    if session is None:
        session = boto3.Session()

    policies = _load_policies()
    rules_by_service: dict[str, list[dict[str, Any]]] = policies.get("rules", {})

    all_violations: list[dict[str, Any]] = []
    total_resources = 0

    for service, rules in rules_by_service.items():
        auditor_cls = _AUDITOR_MAP.get(service)
        if auditor_cls is None:
            log.warning("evaluator.unknown_service", service=service)
            continue

        log.info("evaluator.starting_audit", service=service, rule_count=len(rules))
        auditor = auditor_cls(session)

        resources = auditor.fetch_resources()
        total_resources += len(resources)

        violations = auditor.evaluate(resources, rules)
        log.info(
            "evaluator.audit_complete",
            service=service,
            resource_count=len(resources),
            violation_count=len(violations),
        )
        all_violations.extend(violations)

    return AuditResult(violations=all_violations, resources_audited=total_resources)
