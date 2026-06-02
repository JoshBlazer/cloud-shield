"""AWS Lambda entry point for CloudShield-Auditor."""

import json
import os
import time
from typing import Any

import boto3
import structlog

from src.engine.evaluator import run_audit
from src.notifications import slack
from src.store import violations as store

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()

SNS_TOPIC_ARN        = os.environ.get("SNS_TOPIC_ARN", "")
CLOUDWATCH_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "CloudShield/Auditor")
AWS_REGION           = os.environ.get("AWS_REGION", "us-east-1")


def _push_metrics(cw: Any, resources_audited: int, violations_found: int, duration_ms: float) -> None:
    try:
        cw.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[
                {"MetricName": "ResourcesAudited", "Value": resources_audited, "Unit": "Count"},
                {"MetricName": "ViolationsFound",  "Value": violations_found,  "Unit": "Count"},
                {"MetricName": "AuditDurationMs",  "Value": duration_ms,       "Unit": "Milliseconds"},
            ],
        )
        log.info("handler.metrics_pushed")
    except Exception as exc:  # noqa: BLE001
        log.error("handler.metrics_push_failed", error=str(exc))


def _publish_email(sns: Any, violations: list[dict[str, Any]]) -> None:
    if not SNS_TOPIC_ARN:
        return
    lines = [
        f"[{v['severity']}] {v['rule_id']} | {v['resource_type']} {v['resource_id']}: {v['reason']}"
        for v in violations
    ]
    subject = f"CloudShield: {len(violations)} violation(s) detected"
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=json.dumps({
                "default": subject,
                "email": f"{subject}\n\n" + "\n".join(lines),
            }),
            MessageStructure="json",
        )
        log.info("handler.email_published", count=len(violations))
    except Exception as exc:  # noqa: BLE001
        log.error("handler.email_publish_failed", error=str(exc))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    log.info("handler.audit_started")
    start = time.time()

    session    = boto3.Session()
    cw_client  = session.client("cloudwatch", region_name=AWS_REGION)
    sns_client = session.client("sns",        region_name=AWS_REGION)

    # Re-open any snoozed violations whose window has expired
    woken = store.wake_snoozed_violations(session)
    if woken:
        log.info("handler.snooze_wakeup", count=woken)

    # Snapshot which violations were active before this run so we can detect resolutions
    pre_run_active_pks = store.get_active_pks(session)

    result            = run_audit(session=session)
    current_violations = result["violations"]
    resources_audited  = result["resources_audited"]
    duration_ms        = (time.time() - start) * 1000

    # Persist every violation found — track new vs already-known
    new_violations: list[dict[str, Any]] = []
    found_pks: set[str] = set()

    for v in current_violations:
        pk = f"{v['rule_id']}#{v['resource_id']}"
        found_pks.add(pk)
        item, is_new = store.upsert_violation(session, v)
        if is_new:
            new_violations.append(item)
            log.critical(
                "infrastructure_drift_detected",
                resource_id=v["resource_id"],
                resource_type=v["resource_type"],
                rule_id=v["rule_id"],
                severity=v["severity"],
                reason=v["reason"],
            )

    # Violations that were active before but not found this run are now resolved
    resolved_pks = pre_run_active_pks - found_pks
    for pk in resolved_pks:
        store.mark_resolved(session, pk)
    if resolved_pks:
        log.info("handler.violations_resolved", count=len(resolved_pks))

    _push_metrics(cw_client, resources_audited, len(current_violations), duration_ms)

    # Alert only on genuinely new violations — skip noise for already-tracked ones
    if new_violations:
        slack.send_new_violations(new_violations)
        _publish_email(sns_client, new_violations)

    if resolved_pks:
        slack.send_resolutions(len(resolved_pks))

    if not current_violations:
        log.info("handler.audit_clean", resources_audited=resources_audited, duration_ms=round(duration_ms, 2))

    return {
        "statusCode": 200,
        "violations":        current_violations,
        "new_violations":    len(new_violations),
        "resolved":          len(resolved_pks),
        "resources_audited": resources_audited,
        "duration_ms":       round(duration_ms, 2),
    }
