"""
Generate a visual HTML audit report from a local CloudShield simulation.

Run:  python scripts/generate_report.py
Opens report.html in the default browser when done.
"""

import json
import os
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.update(
    {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "SNS_TOPIC_ARN": "",
        "CLOUDWATCH_NAMESPACE": "CloudShield/Auditor",
        "AWS_REGION": "us-east-1",
    }
)

import boto3
from moto import mock_aws


# ── Seed helpers (same environment as local_run.py) ───────────────────────────

def seed_environment(session):
    s3  = session.client("s3")
    ec2 = session.client("ec2")
    iam = session.client("iam")

    s3.create_bucket(Bucket="acme-raw-data-prod")

    s3.create_bucket(Bucket="acme-uploads-prod")
    s3.put_bucket_encryption(
        Bucket="acme-uploads-prod",
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    s3.put_bucket_versioning(
        Bucket="acme-uploads-prod",
        VersioningConfiguration={"Status": "Enabled"},
    )

    s3.create_bucket(Bucket="acme-backups-prod")
    s3.put_public_access_block(
        Bucket="acme-backups-prod",
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket="acme-backups-prod",
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    s3.put_bucket_versioning(
        Bucket="acme-backups-prod",
        VersioningConfiguration={"Status": "Enabled"},
    )

    resp = ec2.create_security_group(GroupName="web-tier-sg", Description="Web tier")
    ec2.authorize_security_group_ingress(
        GroupId=resp["GroupId"],
        IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        }],
    )

    resp2 = ec2.create_security_group(GroupName="dev-sandbox-sg", Description="Dev sandbox")
    ec2.authorize_security_group_ingress(
        GroupId=resp2["GroupId"],
        IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
    )

    iam.create_user(UserName="alice")
    iam.create_login_profile(UserName="alice", Password="Temp1234!", PasswordResetRequired=True)

    iam.create_user(UserName="bob")
    iam.create_login_profile(UserName="bob", Password="Temp1234!", PasswordResetRequired=False)
    serial = iam.create_virtual_mfa_device(VirtualMFADeviceName="bob-mfa")[
        "VirtualMFADevice"]["SerialNumber"]
    iam.enable_mfa_device(
        UserName="bob", SerialNumber=serial,
        AuthenticationCode1="123456", AuthenticationCode2="789012",
    )

    iam.create_user(UserName="ci-runner")
    iam.create_access_key(UserName="ci-runner")

    sns = session.client("sns")
    arn = sns.create_topic(Name="cloudshield-alerts-test")["TopicArn"]
    os.environ["SNS_TOPIC_ARN"] = arn


# ── HTML generation ──────────────────────────────────────────────────────────

SEVERITY_COLOR = {
    "CRITICAL": ("#ff4d4f", "#fff1f0", "#ff7875"),
    "HIGH":     ("#fa8c16", "#fff7e6", "#ffc069"),
    "MEDIUM":   ("#fadb14", "#feffe6", "#ffe58f"),
    "LOW":      ("#52c41a", "#f6ffed", "#95de64"),
}

RESOURCE_ICON = {
    "AWS::S3::Bucket":          "&#128191;",  # floppy disk
    "AWS::EC2::SecurityGroup":  "&#128737;",  # shield
    "AWS::IAM::User":           "&#128100;",  # person
    "AWS::IAM::AccessKey":      "&#128273;",  # key
    "AWS::IAM::PasswordPolicy": "&#128274;",  # lock
}


def _donut_svg(critical, high, medium, total_violations):
    """Simple SVG donut showing violation breakdown by severity."""
    if total_violations == 0:
        return '<svg width="120" height="120" viewBox="0 0 120 120"><circle cx="60" cy="60" r="45" fill="none" stroke="#52c41a" stroke-width="18"/><text x="60" y="65" text-anchor="middle" font-size="14" fill="#52c41a" font-weight="bold">Clean</text></svg>'

    import math
    segments = [
        (critical, "#ff4d4f"),
        (high,     "#fa8c16"),
        (medium,   "#fadb14"),
        (total_violations - critical - high - medium, "#52c41a"),
    ]
    segments = [(v, c) for v, c in segments if v > 0]

    cx, cy, r, stroke_w = 60, 60, 45, 18
    circumference = 2 * math.pi * r
    paths = []
    offset = 0
    for count, color in segments:
        dash = (count / total_violations) * circumference
        paths.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_w}" stroke-dasharray="{dash:.1f} {circumference:.1f}" '
            f'stroke-dashoffset="{-offset:.1f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash

    label = str(total_violations)
    return (
        f'<svg width="120" height="120" viewBox="0 0 120 120">'
        + "".join(paths)
        + f'<text x="{cx}" y="{cy - 6}" text-anchor="middle" font-size="22" fill="#f0f0f0" font-weight="bold">{label}</text>'
        + f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="10" fill="#8c8c8c">violations</text>'
        + "</svg>"
    )


def _severity_bar(violations):
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for v in violations:
        counts[v["severity"]] = counts.get(v["severity"], 0) + 1
    total = sum(counts.values()) or 1
    bars = ""
    for sev, (bg, _, _) in SEVERITY_COLOR.items():
        pct = (counts[sev] / total) * 100
        if pct > 0:
            bars += f'<div style="width:{pct:.1f}%;background:{bg};height:100%;display:inline-block;"></div>'
    return bars, counts


def render_html(result, timestamp):
    violations = result["violations"]
    resources_audited = result["resources_audited"]
    duration_ms = result["duration_ms"]

    by_sev = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
    for v in violations:
        by_sev.setdefault(v["severity"], []).append(v)

    crit  = len(by_sev["CRITICAL"])
    high  = len(by_sev["HIGH"])
    med   = len(by_sev["MEDIUM"])
    total = len(violations)

    donut = _donut_svg(crit, high, med, total)
    bar_html, counts = _severity_bar(violations)
    status_color = "#ff4d4f" if crit > 0 else ("#fa8c16" if high > 0 else "#52c41a")
    status_text  = "VIOLATIONS DETECTED" if total > 0 else "ALL CLEAR"

    # violation cards
    cards_html = ""
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        group = by_sev.get(sev, [])
        if not group:
            continue
        bg, light, border = SEVERITY_COLOR[sev]
        cards_html += f"""
        <div class="sev-section">
          <h3 style="color:{bg};margin:32px 0 12px;font-size:13px;letter-spacing:2px;text-transform:uppercase;">
            {sev} &mdash; {len(group)} finding{'s' if len(group) != 1 else ''}
          </h3>
        """
        for v in group:
            icon = RESOURCE_ICON.get(v["resource_type"], "&#9679;")
            cards_html += f"""
          <div class="card" style="border-left:4px solid {bg};">
            <div class="card-header">
              <span class="sev-badge" style="background:{bg};">{sev}</span>
              <span class="rule-id">{v['rule_id']}</span>
              <span class="rule-name">{v['rule_name']}</span>
            </div>
            <div class="card-body">
              <div class="resource-line">
                <span class="icon">{icon}</span>
                <span class="rtype">{v['resource_type']}</span>
                <code class="rid">{v['resource_id']}</code>
              </div>
              <div class="reason">{v['reason']}</div>
            </div>
          </div>
            """
        cards_html += "</div>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CloudShield Audit Report</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
    background: #0d0d0d; color: #d9d9d9; min-height: 100vh;
  }}
  .topbar {{
    background: #141414; border-bottom: 1px solid #262626;
    padding: 14px 32px; display: flex; align-items: center; gap: 16px;
  }}
  .topbar .logo {{ font-size: 20px; font-weight: 700; color: #fff; letter-spacing: -0.5px; }}
  .topbar .logo span {{ color: {status_color}; }}
  .topbar .ts {{ margin-left: auto; font-size: 12px; color: #595959; }}
  .status-banner {{
    background: linear-gradient(135deg, #1a1a1a 0%, #141414 100%);
    border-bottom: 1px solid #262626;
    padding: 28px 32px; display: flex; align-items: center; gap: 40px;
  }}
  .status-badge {{
    font-size: 13px; font-weight: 700; letter-spacing: 2px;
    color: {status_color}; border: 1.5px solid {status_color};
    padding: 6px 14px; border-radius: 4px; white-space: nowrap;
  }}
  .donut {{ flex-shrink: 0; }}
  .legend {{ display: flex; flex-direction: column; gap: 6px; }}
  .legend-row {{ display: flex; align-items: center; gap: 8px; font-size: 13px; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .stats {{ display: flex; gap: 24px; margin-left: auto; flex-wrap: wrap; }}
  .stat-box {{
    background: #1a1a1a; border: 1px solid #262626; border-radius: 8px;
    padding: 16px 24px; text-align: center; min-width: 110px;
  }}
  .stat-box .num {{ font-size: 32px; font-weight: 700; line-height: 1; }}
  .stat-box .lbl {{ font-size: 11px; color: #595959; margin-top: 4px; text-transform: uppercase; letter-spacing: 1px; }}
  .bar-wrap {{
    background: #1a1a1a; border-bottom: 1px solid #262626;
    padding: 10px 32px; display: flex; align-items: center; gap: 12px;
  }}
  .bar-track {{ flex: 1; height: 6px; background: #262626; border-radius: 3px; overflow: hidden; }}
  .bar-lbl {{ font-size: 11px; color: #595959; white-space: nowrap; }}
  .main {{ max-width: 960px; margin: 0 auto; padding: 24px 32px 64px; }}
  .card {{
    background: #141414; border: 1px solid #262626; border-radius: 8px;
    margin-bottom: 10px; overflow: hidden;
    transition: border-color 0.15s;
  }}
  .card:hover {{ border-color: #434343; }}
  .card-header {{
    padding: 12px 16px; display: flex; align-items: center; gap: 10px;
    background: #1a1a1a; border-bottom: 1px solid #262626;
  }}
  .sev-badge {{
    font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
    padding: 2px 8px; border-radius: 3px; color: #000; white-space: nowrap;
  }}
  .rule-id {{ font-size: 12px; color: #8c8c8c; font-family: monospace; }}
  .rule-name {{ font-size: 13px; color: #d9d9d9; font-weight: 500; }}
  .card-body {{ padding: 12px 16px; }}
  .resource-line {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .icon {{ font-size: 16px; }}
  .rtype {{ font-size: 11px; color: #595959; }}
  .rid {{
    font-family: monospace; font-size: 12px; color: #69c0ff;
    background: #111d2c; padding: 1px 6px; border-radius: 3px;
  }}
  .reason {{ font-size: 13px; color: #8c8c8c; line-height: 1.5; }}
  .footer {{
    text-align: center; font-size: 11px; color: #434343;
    padding: 24px; border-top: 1px solid #1a1a1a; margin-top: 32px;
  }}
  h3 {{ }}
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">Cloud<span>Shield</span> Auditor</div>
  <div style="font-size:12px;color:#434343;">Infrastructure Drift &amp; Compliance Report</div>
  <div class="ts">Generated {timestamp}</div>
</div>

<div class="status-banner">
  <div class="status-badge">{status_text}</div>
  <div class="donut">{donut}</div>
  <div class="legend">
    {''.join(f'<div class="legend-row"><div class="legend-dot" style="background:{SEVERITY_COLOR[s][0]};"></div><span style="color:#8c8c8c;font-size:12px;">{s}</span><span style="margin-left:auto;padding-left:16px;font-weight:600;color:{SEVERITY_COLOR[s][0]};">{counts.get(s,0)}</span></div>' for s in ("CRITICAL","HIGH","MEDIUM","LOW"))}
  </div>
  <div class="stats">
    <div class="stat-box">
      <div class="num" style="color:#d9d9d9;">{resources_audited}</div>
      <div class="lbl">Resources Audited</div>
    </div>
    <div class="stat-box">
      <div class="num" style="color:{status_color};">{total}</div>
      <div class="lbl">Total Violations</div>
    </div>
    <div class="stat-box">
      <div class="num" style="color:#8c8c8c;">{duration_ms:.0f}<span style="font-size:14px;">ms</span></div>
      <div class="lbl">Audit Duration</div>
    </div>
  </div>
</div>

<div class="bar-wrap">
  <span class="bar-lbl">Severity breakdown</span>
  <div class="bar-track">{bar_html}</div>
  <span class="bar-lbl">{total} finding{'s' if total != 1 else ''}</span>
</div>

<div class="main">
  {cards_html if cards_html else '<p style="text-align:center;color:#52c41a;padding:48px;">No violations detected. Infrastructure is compliant.</p>'}
</div>

<div class="footer">
  CloudShield-Auditor &nbsp;&bull;&nbsp; {resources_audited} resources &nbsp;&bull;&nbsp;
  Rules: S3_001-003 &nbsp;|&nbsp; IAM_001-003 &nbsp;|&nbsp; EC2_001-004 &nbsp;&bull;&nbsp;
  {duration_ms:.0f}ms
</div>

</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    with mock_aws():
        session = boto3.Session(region_name="us-east-1")
        seed_environment(session)

        from src.handler import lambda_handler
        result = lambda_handler({}, context=None)

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    html = render_html(result, ts)

    out = Path(__file__).parent.parent / "report.html"
    out.write_text(html, encoding="utf-8")

    print(f"Report written to: {out}")
    print(f"  {result['resources_audited']} resources audited")
    print(f"  {len(result['violations'])} violations found")
    print(f"  {result['duration_ms']:.0f}ms")

    webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
