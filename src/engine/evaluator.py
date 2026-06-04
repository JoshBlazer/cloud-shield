"""Policy evaluator — runs all auditors against one or more account/region targets."""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

import boto3
import structlog
import yaml

from src.auditors.base_auditor import BaseAuditor
from src.auditors.ec2_auditor import EC2Auditor
from src.auditors.iam_auditor import IAMAuditor
from src.auditors.s3_auditor import S3Auditor

log = structlog.get_logger()

_POLICY_PATH = Path(__file__).parent.parent.parent / "policies.yaml"

# Concrete auditor factories keyed by service. Typed as a Callable (not type[...])
# so mypy treats each as a factory returning a BaseAuditor rather than an
# attempt to instantiate the abstract base.
_AUDITOR_MAP: dict[str, Callable[[Any], BaseAuditor]] = {
    "s3":  S3Auditor,
    "ec2": EC2Auditor,
    "iam": IAMAuditor,
}


class AuditResult(TypedDict):
    violations: list[dict[str, Any]]
    resources_audited: int


def _load_policies(path: Path = _POLICY_PATH) -> dict[str, Any]:
    with open(path) as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
        return data


def _assume_role_session(base_session: Any, role_arn: str, account_id: str, region: str) -> Any:
    """Assume a cross-account role and return a boto3 Session for that account."""
    sts   = base_session.client("sts")
    creds = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=f"cloudshield-audit-{account_id}",
        DurationSeconds=3600,
    )["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region or None,
    )


def _audit_target(
    session: Any,
    account_id: str,
    region: str,
    rules_by_service: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], int]:
    """Run all auditors for one account/region. Returns (violations, resources_audited)."""
    all_violations: list[dict[str, Any]] = []
    total_resources = 0

    for service, rules in rules_by_service.items():
        auditor_cls = _AUDITOR_MAP.get(service)
        if auditor_cls is None:
            log.warning("evaluator.unknown_service", service=service)
            continue

        log.info("evaluator.starting_audit", service=service, account=account_id, region=region)
        auditor   = auditor_cls(session)
        resources = auditor.fetch_resources()
        total_resources += len(resources)

        violations = auditor.evaluate(resources, rules)
        # Tag every violation with the account and region it came from
        for v in violations:
            v.setdefault("account_id", account_id)
            v.setdefault("region", region)

        log.info(
            "evaluator.audit_complete",
            service=service, account=account_id, region=region,
            resources=len(resources), violations=len(violations),
        )
        all_violations.extend(violations)

    return all_violations, total_resources


def run_audit(
    session: Any = None,
    targets: list[dict[str, str]] | None = None,
) -> AuditResult:
    """
    Run security audits across one or more account/region targets.

    targets: list of {"account_id": str, "region": str, "role_arn": str (optional)}
             If None, reads AUDIT_TARGETS env var (JSON array).
             Falls back to auditing the current account/region with the default session.

    Cross-account: when role_arn is set, assumes that role via STS and audits using
    the resulting temporary credentials. The base session needs sts:AssumeRole.
    """
    if session is None:
        session = boto3.Session()

    if targets is None:
        raw = os.environ.get("AUDIT_TARGETS", "[]")
        try:
            targets = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            targets = []

    if not targets:
        # Default: audit current account/region
        targets = [{"account_id": "", "region": "", "role_arn": ""}]

    policies        = _load_policies()
    rules_by_service = policies.get("rules", {})

    all_violations: list[dict[str, Any]] = []
    total_resources = 0

    default_account = os.environ.get("AWS_ACCOUNT_ID", "")
    default_region  = os.environ.get("AWS_REGION", "us-east-1")

    for target in targets:
        account_id = target.get("account_id") or default_account
        region     = target.get("region")     or default_region
        role_arn   = target.get("role_arn",   "")

        try:
            target_session = (
                _assume_role_session(session, role_arn, account_id, region)
                if role_arn else session
            )
        except Exception as exc:  # noqa: BLE001
            log.error("evaluator.assume_role_failed", account=account_id, role=role_arn, error=str(exc))
            continue

        violations, resources = _audit_target(target_session, account_id, region, rules_by_service)
        all_violations.extend(violations)
        total_resources += resources

    return AuditResult(violations=all_violations, resources_audited=total_resources)
