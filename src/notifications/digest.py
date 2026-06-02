"""Weekly SES digest Lambda — generates and sends an executive summary email."""

import os
from datetime import UTC, datetime
from typing import Any

import boto3
import structlog

from src.store.violations import get_summary

log = structlog.get_logger()

SES_FROM    = os.environ.get("DIGEST_FROM_EMAIL", "cloudshield@example.com")
SES_TO      = os.environ.get("DIGEST_TO_EMAIL", "")
AWS_REGION  = os.environ.get("AWS_REGION", "us-east-1")
DASH_URL    = os.environ.get("DASHBOARD_URL", "https://cloudshield.example.com")


def _render_html(summary: dict[str, Any], date_range: str) -> str:
    by_sev    = summary.get("by_severity", {})
    by_status = summary.get("by_status", {})
    by_team   = summary.get("by_team", {})
    total     = summary.get("total", 0)
    open_ct   = by_status.get("OPEN", 0)
    resolved  = by_status.get("RESOLVED", 0)
    critical  = by_sev.get("CRITICAL", 0)

    team_rows = "".join(
        f"<tr><td>{team}</td>"
        f"<td style='color:#ff4d4f;font-weight:bold'>{counts.get('OPEN', 0)}</td>"
        f"<td style='color:#fa8c16'>{counts.get('ACKNOWLEDGED', 0)}</td>"
        f"<td style='color:#52c41a'>{counts.get('RESOLVED', 0)}</td></tr>"
        for team, counts in sorted(by_team.items(), key=lambda x: x[1].get("OPEN", 0), reverse=True)
    )

    return f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,sans-serif;background:#f5f5f5;padding:32px;">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <div style="background:#141414;padding:24px 32px;">
    <h1 style="color:#fff;margin:0;font-size:20px;">Cloud<span style="color:#ff4d4f">Shield</span> Weekly Report</h1>
    <p style="color:#595959;margin:4px 0 0;font-size:13px;">{date_range}</p>
  </div>
  <div style="padding:24px 32px;">
    <div style="display:flex;gap:16px;margin-bottom:24px;">
      {''.join(f'<div style="flex:1;background:#f5f5f5;border-radius:8px;padding:16px;text-align:center"><div style="font-size:28px;font-weight:700;color:{c}">{n}</div><div style="font-size:11px;color:#8c8c8c;text-transform:uppercase;letter-spacing:1px">{lbl}</div></div>'
        for n, lbl, c in [
            (open_ct, "Open", "#ff4d4f"),
            (resolved, "Resolved", "#52c41a"),
            (critical, "Critical", "#ff4d4f"),
            (total, "Total", "#595959"),
        ])}
    </div>
    <h3 style="font-size:13px;color:#8c8c8c;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Team Breakdown</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="background:#f5f5f5">
        <th style="text-align:left;padding:8px">Team</th>
        <th style="text-align:left;padding:8px">Open</th>
        <th style="text-align:left;padding:8px">Acknowledged</th>
        <th style="text-align:left;padding:8px">Resolved</th>
      </tr></thead>
      <tbody>{team_rows or '<tr><td colspan="4" style="padding:8px;color:#8c8c8c">No violations this week</td></tr>'}</tbody>
    </table>
    <div style="margin-top:24px;text-align:center">
      <a href="{DASH_URL}" style="background:#ff4d4f;color:#fff;padding:10px 24px;border-radius:4px;text-decoration:none;font-size:13px;font-weight:600">Open Dashboard</a>
    </div>
  </div>
  <div style="padding:16px 32px;background:#f5f5f5;font-size:11px;color:#8c8c8c;text-align:center">
    CloudShield-Auditor &nbsp;·&nbsp; Automated security posture report
  </div>
</div>
</body></html>"""


def digest_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if not SES_TO:
        log.warning("digest.no_recipient_configured")
        return {"statusCode": 400, "body": "DIGEST_TO_EMAIL not set"}

    session = boto3.Session()
    summary = get_summary(session)

    now   = datetime.now(tz=UTC)
    range_str = f"Week of {now.strftime('%B %d, %Y')}"
    html  = _render_html(summary, range_str)

    ses = session.client("ses", region_name=AWS_REGION)
    ses.send_email(
        Source=SES_FROM,
        Destination={"ToAddresses": [SES_TO]},
        Message={
            "Subject": {"Data": f"CloudShield Weekly — {range_str}"},
            "Body": {"Html": {"Data": html}},
        },
    )
    log.info("digest.sent", to=SES_TO)
    return {"statusCode": 200, "body": "digest sent"}
