# CloudShield-Auditor

Scheduled Lambda that evaluates your AWS account against a declarative security ruleset every hour. New violations land in DynamoDB and trigger a Slack alert. Resources that get fixed are automatically resolved. A React dashboard gives three different views of the same data depending on who's looking.

## Architecture

```
EventBridge (hourly)
    └─ Auditor Lambda ──► S3 / EC2 / IAM APIs (parallel per-resource)
                    ├──► DynamoDB  (upsert violations, mark resolved)
                    ├──► Slack     (Block Kit alerts — new violations only)
                    └──► SNS → SES (optional email fan-out)

API Gateway HTTP API (v2, payload format 1.0)
    └─ API Lambda ──► DynamoDB (CRUD + lifecycle)
                └──► Auditor Lambda (async invoke via /audit/trigger)

React Dashboard (CloudFront + S3, SPA routing)
    ├── Violations   — grouped by severity, filter by status/severity
    ├── My Resources — team-scoped view with inline fix instructions
    └── Posture      — compliance ring, 7-day trend, team breakdown
```

### Key design decisions

**Upsert pattern.** Violations use `{rule_id}#{resource_id}` as the DynamoDB partition key. Re-detected violations increment `occurrence_count` and update `last_seen` without creating noise. A violation is only new once — subsequent identical findings silently update. When the resource passes the check, the item is marked `RESOLVED`.

**Alert fatigue prevention.** Slack messages are sent only when `is_new=True` from the upsert. Already-tracked violations never re-alert unless they resolve and reappear.

**Tag-based routing.** AWS resource tags `team` and `owner` propagate into every violation record. The dashboard's "My Resources" view filters by team, and the weekly digest groups findings by team automatically.

**No static AWS credentials.** CI/CD uses OIDC — GitHub Actions assumes a role via short-lived tokens. No `AWS_ACCESS_KEY_ID` in secrets.

## Security rules

| ID | Service | Severity | What it checks |
|---|---|---|---|
| S3_001 | S3 | CRITICAL | All four PublicAccessBlock settings enabled |
| S3_002 | S3 | HIGH | Default server-side encryption configured |
| S3_003 | S3 | MEDIUM | Versioning enabled |
| S3_004 | S3 | CRITICAL | Bucket policy doesn't grant `Principal: "*"` |
| IAM_001 | IAM | CRITICAL | Console users have MFA devices |
| IAM_002 | IAM | HIGH | Access keys rotated within 90 days |
| IAM_003 | IAM | HIGH | Account password policy meets complexity requirements |
| IAM_004 | IAM | CRITICAL | Root account has MFA enabled |
| EC2_001 | EC2 | CRITICAL | No security group allows SSH (22) from 0.0.0.0/0 |
| EC2_002 | EC2 | CRITICAL | No security group allows RDP (3389) from 0.0.0.0/0 |
| EC2_003 | EC2 | CRITICAL | No security group allows all traffic from any source |
| EC2_004 | EC2 | MEDIUM | No security group allows HTTP (80) from 0.0.0.0/0 |

Rules are defined in `policies.yaml`. Adding a new rule is one YAML entry plus a `check` handler in the corresponding auditor.

## Local development

```bash
# Python backend
pip install -r requirements-dev.txt
make test          # 60 tests
make lint          # ruff
make type-check    # mypy

# Simulate a full audit run against mocked AWS
python scripts/local_run.py

# Dashboard (mock API, no AWS needed)
cd dashboard
npm install
npm run dev        # http://localhost:5173
```

## Deploy to AWS

### First time (one per account)

```bash
# 1. Bootstrap OIDC trust (creates the GitHub Actions role)
make bootstrap GITHUB_ORG=your-org-name

# 2. Deploy the stack
make deploy-guided SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

`deploy-guided` walks through `sam deploy --guided` and saves answers to `samconfig.toml`. Subsequent deploys just run `make deploy`.

### Optional parameters

| Parameter | Default | Purpose |
|---|---|---|
| `SlackWebhookUrl` | required | Incoming webhook for Block Kit alerts |
| `ApiKey` | _(empty)_ | Pre-shared key for `X-Api-Key` header auth on the API |
| `SlackSigningSecret` | _(empty)_ | Verifies Slack callback signatures |
| `DigestToEmail` | _(empty)_ | Enable weekly SES digest to this address |
| `DigestFromEmail` | `cloudshield-noreply@example.com` | Verified SES sender |
| `AuditScheduleExpression` | `rate(1 hour)` | How often to run |
| `Environment` | `production` | Suffix on all resource names |

### Dashboard deploy

After the stack is up:

```bash
make dashboard-deploy
# Reads DashboardBucketName and ApiEndpoint from CloudFormation outputs automatically
```

### CI/CD

Push to `main` → GitHub Actions builds and deploys automatically using OIDC (no static keys). See `.github/workflows/deploy.yml`.

## Violation lifecycle

```
OPEN ──► ACKNOWLEDGED  (someone saw it)
     ──► SNOOZED       (suppressed for N days)
     ──► EXEMPTED      (policy exception, permanent)

Any active status ──► RESOLVED  (resource fixed, detected next audit)
RESOLVED ──► OPEN               (regression — re-detected after resolution)
```

Lifecycle transitions are available via the dashboard UI, Slack buttons, or `PATCH /violations/{id}`.

## API reference

All endpoints require `X-Api-Key: <key>` when `ApiKey` is configured.

| Method | Path | Description |
|---|---|---|
| GET | `/violations` | List violations. Filters: `?status=OPEN&severity=CRITICAL&team=infra` |
| GET | `/violations/{id}` | Get one violation by `violation_id` |
| PATCH | `/violations/{id}` | Lifecycle action: `{"action": "acknowledge"/"snooze"/"exempt"}` |
| GET | `/summary` | Aggregate counts by status, severity, and team |
| POST | `/audit/trigger` | Queue an out-of-cycle audit run (async, returns 202) |
| POST | `/slack/interact` | Slack interactivity callback (Ack/Snooze buttons) |

## Project layout

```
src/
  auditors/       base_auditor.py + s3/ec2/iam auditors
  engine/         evaluator.py — orchestrates auditors, returns AuditResult
  store/          violations.py — DynamoDB CRUD and lifecycle
  notifications/  slack.py + digest.py
  api/            handler.py — API Gateway Lambda
  handler.py      main Lambda entrypoint (scheduled auditor)
dashboard/        React + Vite + TypeScript + Tailwind + Recharts
tests/            60 tests (moto-based, no real AWS needed)
policies.yaml     declarative rule definitions
template.yaml     SAM IaC (DynamoDB, Lambda, API GW, CloudFront, S3)
```

## Known limitations

- Single account, single region. Cross-account org-wide scanning would require assuming roles per account.
- `get_summary` uses a DynamoDB scan — fine for thousands of violations, needs a counter table at scale.
- No CloudTrail, RDS, KMS, or EBS rules yet — the auditor pattern makes adding them straightforward.
