from typing import Any

import structlog
from botocore.exceptions import ClientError

from .base_auditor import BaseAuditor

log = structlog.get_logger()

_OPEN_CIDRS = {"0.0.0.0/0", "::/0"}


class EC2Auditor(BaseAuditor):
    """Audits EC2 security groups for dangerously permissive ingress rules."""

    def __init__(self, session: Any) -> None:
        super().__init__(session)
        self._client = session.client("ec2")

    def fetch_resources(self) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []

        try:
            paginator = self._client.get_paginator("describe_security_groups")
            for page in paginator.paginate():
                for sg in page.get("SecurityGroups", []):
                    resources.append(sg)
                    log.debug("ec2.fetched_sg", sg_id=sg["GroupId"])
        except ClientError as exc:
            log.error("ec2.describe_security_groups failed", error=str(exc))

        return resources

    def evaluate(
        self, resources: list[dict[str, Any]], rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        for sg in resources:
            sg_id   = sg["GroupId"]
            sg_name = sg.get("GroupName", sg_id)
            ingress_rules = sg.get("IpPermissions", [])
            tags = {tag["Key"]: tag["Value"] for tag in sg.get("Tags", [])}
            sg_tags = {"team": tags.get("team", "untagged"), "owner": tags.get("owner")}

            for rule in rules:
                check = rule.get("check")

                if check == "unrestricted_ingress":
                    target_port = rule.get("port")
                    if target_port is None:
                        continue
                    found = self._has_unrestricted_port(ingress_rules, target_port)
                    if found:
                        violations.append(
                            self._build_violation(
                                rule, sg_id,
                                f"Security group '{sg_name}' allows port {target_port} from {found}",
                                sg_tags,
                            )
                        )

                elif check == "unrestricted_all_traffic":
                    for perm in ingress_rules:
                        if perm.get("IpProtocol") == "-1":
                            open_cidr = self._get_open_cidr(perm)
                            if open_cidr:
                                violations.append(
                                    self._build_violation(
                                        rule, sg_id,
                                        f"Security group '{sg_name}' allows all traffic from {open_cidr}",
                                        sg_tags,
                                    )
                                )
                                break

        return violations

    def _has_unrestricted_port(
        self, permissions: list[dict[str, Any]], port: int
    ) -> str:
        """Returns the offending CIDR if the port is open to the world, else empty string."""
        for perm in permissions:
            protocol = perm.get("IpProtocol", "")
            # -1 means all protocols/ports; tcp/udp use from/to port range
            if protocol not in ("-1", "tcp", "udp", "6", "17"):
                continue

            from_port = perm.get("FromPort", 0)
            to_port = perm.get("ToPort", 65535)

            if protocol == "-1" or (from_port <= port <= to_port):
                open_cidr = self._get_open_cidr(perm)
                if open_cidr:
                    return open_cidr

        return ""

    @staticmethod
    def _get_open_cidr(perm: dict[str, Any]) -> str:
        for ip_range in perm.get("IpRanges", []):
            if ip_range.get("CidrIp") in _OPEN_CIDRS:
                return str(ip_range["CidrIp"])
        for ip_range in perm.get("Ipv6Ranges", []):
            if ip_range.get("CidrIpv6") in _OPEN_CIDRS:
                return str(ip_range["CidrIpv6"])
        return ""

    @staticmethod
    def _build_violation(
        rule: dict[str, Any], resource_id: str, reason: str, tags: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "rule_id":       rule["id"],
            "rule_name":     rule["name"],
            "severity":      rule["severity"],
            "resource_type": "AWS::EC2::SecurityGroup",
            "resource_id":   resource_id,
            "reason":        reason,
            "team":          (tags or {}).get("team", "untagged"),
            "owner":         (tags or {}).get("owner"),
        }
