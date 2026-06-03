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

Lifecycle transitions are available via the dashboard UI, Slack buttons, or `PATCH /violations/{id}`. Snoozes auto-expire: the auditor re-opens any snoozed violation past its `snooze_until` at the start of each run. Every transition (who, what, when, from→to) is written to a separate `cloudshield-audit-log` table and shown as a timeline on each violation card.

## Authentication

Two layers, picked per caller:

- **Dashboard users** sign in through a Cognito hosted UI (OAuth2 + PKCE, no client secret). The SPA holds the resulting token in memory only (never localStorage) and sends it as `Authorization: Bearer <jwt>`. The API validates the signature against the Cognito JWKS, checks the `iss` claim equals the expected issuer, and confirms the client by `token_use`: ID tokens must have `aud == client_id`, access tokens must have `client_id == client_id` (Cognito access tokens carry no `aud`). The JWKS is cached with a 1-hour TTL and force-refreshed when a token's `kid` isn't in the cache, so Cognito signing-key rotation is picked up without recycling the container. This solves the "static SPA can't hold a secret" problem — there's no long-lived key in the bundle.
- **Machine-to-machine** callers (CI, scripts) send `X-Api-Key: <key>`, checked in constant time.

When neither an API key nor `COGNITO_ISSUER` is configured (local dev), auth passes through.

**Secrets.** The Slack webhook, API key, and Slack signing secret live in AWS Secrets Manager and are fetched at Lambda cold start (`src/config/secrets.py`), cached for the container's life. They are never placed in Lambda environment variables, so they don't appear in the function configuration. The `NoEcho` CloudFormation parameters only seed the secret on first deploy — rotate later with `aws secretsmanager put-secret-value` and leave the params empty on subsequent deploys.

## Multi-account, multi-region

The auditor scans a list of targets read from the `AuditTargetAccounts` parameter (JSON):

```json
[
  {"account_id": "111122223333", "region": "us-east-1", "role_arn": "arn:aws:iam::111122223333:role/CloudShieldAuditRole"},
  {"account_id": "444455556666", "region": "eu-west-1", "role_arn": "arn:aws:iam::444455556666:role/CloudShieldAuditRole"}
]
```

For each target with a `role_arn`, the auditor assumes that role via STS and scans using the temporary credentials. Every violation is tagged with its `account_id` and `region`. Deploy `member-account-role.yaml` into each account you want scanned — it creates a read-only `CloudShieldAuditRole` trusting the central account (optionally hardened with an `ExternalId`). With no targets configured, the auditor falls back to scanning its own account and region.

## Reliability

- The auditor runs with `ReservedConcurrentExecutions: 1` so the hourly schedule and a manual `/audit/trigger` can never interleave their resolve-diff logic.
- All three Lambdas and both EventBridge schedules have an SQS dead-letter queue (`cloudshield-dlq`, 14-day retention) — a failed run lands there for inspection and replay rather than vanishing.
- `active-pk-index` is a sparse GSI: only OPEN/ACKNOWLEDGED/SNOOZED items carry the `active_pk` attribute, so RESOLVED/EXEMPTED rows drop off the index entirely. This keeps active-violation queries off a hot low-cardinality partition and shrinks the index.
- Resolved violations get a 90-day DynamoDB TTL so the hot table stays bounded.

## API reference

Every endpoint accepts either `X-Api-Key: <key>` or `Authorization: Bearer <cognito-jwt>`.

| Method | Path | Description |
|---|---|---|
| GET | `/violations` | List violations. Filters: `?status=OPEN&severity=CRITICAL&team=infra` |
| GET | `/violations/{id}` | Get one violation by `violation_id` |
| GET | `/violations/{id}/history` | Lifecycle audit trail for one violation, newest first |
| PATCH | `/violations/{id}` | Lifecycle action: `{"action": "acknowledge"/"snooze"/"exempt"}` |
| GET | `/summary` | Aggregate counts by status, severity, and team |
| POST | `/audit/trigger` | Queue an out-of-cycle audit run (async, returns 202) |
| POST | `/slack/interact` | Slack interactivity callback (signature-verified) |

## Project layout

```
src/
  auditors/       base_auditor.py + s3/ec2/iam auditors
  engine/         evaluator.py — multi-account/region orchestration
  store/          violations.py (CRUD + lifecycle), audit_log.py (transition trail)
  config/         secrets.py — Secrets Manager loader (cold-start, cached)
  notifications/  slack.py + digest.py
  api/            handler.py — API Gateway Lambda (API key + Cognito JWT auth)
  handler.py      main Lambda entrypoint (scheduled auditor)
dashboard/        React + Vite + TypeScript + Tailwind + Recharts
  src/hooks/      useAuth.ts — Cognito PKCE flow
tests/            88 tests (moto-based, no real AWS needed)
policies.yaml         declarative rule definitions
template.yaml         SAM IaC (DynamoDB, Lambda, API GW, CloudFront, Cognito, SQS, Secrets)
member-account-role.yaml  read-only role to deploy in each scanned account
```

## Known limitations

- `get_summary` still uses a DynamoDB scan — fine for thousands of violations, but at much larger scale it should move to a maintained counter table.
- No CloudTrail, RDS, KMS, or EBS rules yet — the auditor pattern makes adding them straightforward.
- The dashboard does not paginate the violation list in the UI; the API caps results at 500 per call.
