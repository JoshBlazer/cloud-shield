from typing import Any

import structlog
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()

_RESOURCE_TYPE = "AWS::RDS::DBInstance"


class RDSAuditor(BaseAuditor):
    """Audits RDS instances for public exposure, encryption at rest, and backups."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("rds")

    def fetch_resources(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            paginator = self._client.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                resources.extend(page.get("DBInstances", []))
        except ClientError as exc:
            log.error("rds.describe_db_instances failed", error=str(exc))
        return resources

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        for db in resources:
            db_id  = db["DBInstanceIdentifier"]
            db_arn = db.get("DBInstanceArn", db_id)
            tags   = {t["Key"]: t["Value"] for t in db.get("TagList", [])}

            for rule in rules:
                check = rule.get("check")

                if check == "rds_publicly_accessible" and db.get("PubliclyAccessible"):
                    violations.append(self.build_violation(
                        rule, _RESOURCE_TYPE, db_arn,
                        f"RDS instance '{db_id}' is publicly accessible",
                        tags,
                    ))

                elif check == "rds_storage_unencrypted" and not db.get("StorageEncrypted"):
                    violations.append(self.build_violation(
                        rule, _RESOURCE_TYPE, db_arn,
                        f"RDS instance '{db_id}' does not have storage encryption enabled",
                        tags,
                    ))

                elif check == "rds_backup_retention_low":
                    min_days  = int(rule.get("min_days", 7))
                    retention = int(db.get("BackupRetentionPeriod", 0))
                    if retention < min_days:
                        violations.append(self.build_violation(
                            rule, _RESOURCE_TYPE, db_arn,
                            f"RDS instance '{db_id}' retains backups for {retention} day(s); "
                            f"minimum is {min_days}",
                            tags,
                        ))

        return violations
