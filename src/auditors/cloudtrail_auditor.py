from typing import Any

import structlog
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()

_TRAIL_TYPE   = "AWS::CloudTrail::Trail"
_ACCOUNT_TYPE = "AWS::::Account"


class CloudTrailAuditor(BaseAuditor):
    """Audits CloudTrail coverage (an active multi-region trail) and trail hardening."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("cloudtrail")

    def fetch_resources(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        try:
            # Shadow trails (multi-region or organization trails homed elsewhere)
            # count toward coverage of this region, but per-trail hardening checks
            # only run where the trail is homed so each trail is judged once.
            trails = self._client.describe_trails(includeShadowTrails=True).get("trailList", [])
        except ClientError as exc:
            log.error("cloudtrail.describe_trails failed", error=str(exc))
            return resources

        for trail in trails:
            trail["IsHome"] = trail.get("HomeRegion", self.region) == self.region
            try:
                status = self._client.get_trail_status(Name=trail["TrailARN"])
                trail["IsLogging"] = bool(status.get("IsLogging"))
            except ClientError as exc:
                log.warning("cloudtrail.get_trail_status failed", trail=trail.get("Name"), error=str(exc))
                trail["IsLogging"] = False
            resources.append(trail)
        return resources

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        home_trails = [t for t in resources if t.get("IsHome", True)]

        for rule in rules:
            check = rule.get("check")

            if check == "cloudtrail_not_enabled":
                covered = any(
                    t.get("IsLogging") and (t.get("IsMultiRegionTrail") or t.get("IsHome", True))
                    for t in resources
                )
                if not covered:
                    violations.append(self.build_violation(
                        rule, _ACCOUNT_TYPE, self.account_resource_id("cloudtrail"),
                        f"No logging CloudTrail trail covers {self.region}",
                    ))

            elif check == "log_file_validation_disabled":
                for t in home_trails:
                    if not t.get("LogFileValidationEnabled"):
                        violations.append(self.build_violation(
                            rule, _TRAIL_TYPE, t["TrailARN"],
                            f"Trail '{t['Name']}' does not have log file validation enabled",
                        ))

            elif check == "trail_not_kms_encrypted":
                for t in home_trails:
                    if not t.get("KmsKeyId"):
                        violations.append(self.build_violation(
                            rule, _TRAIL_TYPE, t["TrailARN"],
                            f"Trail '{t['Name']}' logs are not encrypted with a KMS key",
                        ))

        return violations
