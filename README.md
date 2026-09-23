# CloudShield-Auditor

Serverless AWS CSPM that continuously audits your accounts against security policies and tracks every finding through its full lifecycle.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![IaC](https://img.shields.io/badge/IaC-AWS%20SAM-FF9900?logo=amazonaws&logoColor=white)
![Dashboard](https://img.shields.io/badge/Dashboard-React%2018-61DAFB?logo=react&logoColor=black)
![Tests](https://img.shields.io/badge/tests-192%20passing-4ade80)
![License](https://img.shields.io/badge/license-MIT-blue)
[![CI](https://github.com/JoshBlazer/cloud-shield/actions/workflows/deploy.yml/badge.svg)](https://github.com/JoshBlazer/cloud-shield/actions/workflows/deploy.yml)

![CloudShield Violations dashboard](docs/screenshots/violations.png)

**Highlights**

- **Continuous auditing.** An hourly EventBridge schedule runs the rule set against live cloud state. No manual scans.
- **Alert de-noising.** You only hear about drift that is genuinely new. Already-tracked findings update silently, so the channel stays signal.
- **Full violation lifecycle.** Every finding moves through acknowledge / snooze / exempt / resolve, with an append-only audit trail of who changed what and when.
- **Multi-account coverage.** A central auditor account assumes read-only roles into member accounts and scans them, tagging each finding with its account and region.

## What it does

Most CSPM clones list findings. The value here is the operating model around them.

Every violation has a deterministic identity: the same misconfiguration keeps one ID (`uuid5` of `rule_id#resource_id`) across every run, so re-detections increment an occurrence count instead of spawning duplicates. The auditor diffs each run against the previous state, which is what lets it tell three situations apart that a naive scanner conflates: a brand-new finding fires an alert, a finding that was resolved and has now reappeared re-alerts (a regression), and a still-failing finding you deliberately exempted stays quiet. That distinction, plus snooze timers that auto-expire and reopen, is the difference between scanning a cloud and operating a security program on it.

## Architecture

```mermaid
flowchart LR
  EB[EventBridge<br/>hourly] --> AUD[Audit Lambda]
  AUD --> EVAL[Evaluator<br/>fan-out]
  EVAL --> A1[S3 auditor]
  EVAL --> A2[EC2 auditor]
  EVAL --> A3[IAM auditor]
  EVAL --> A4[CloudTrail / RDS /<br/>KMS / EBS auditors]
  EVAL -. STS assume-role .-> ACCTS[(member accounts<br/>+ regions)]
  AUD --> DDB[(DynamoDB<br/>violation store)]
  AUD --> DIFF{drift diff}
  DIFF -->|new / regressed| ALERT[Slack + SNS/SES]
  DIFF -->|resolved| ALERT
  AUD --> LOG[(audit-log table)]
  AUD --> SUM[(summary<br/>aggregate)]
  AUD -. failures .-> DLQ[(SQS DLQ)]
  DLQ --> CWALARM[CloudWatch alarm]

  USER([Dashboard user]) --> CF[CloudFront + S3<br/>React SPA]
  CF --> COG[Cognito hosted UI]
  CF --> API[API Lambda]
  API --> DDB
  API --> SUM
  API -. /audit/trigger .-> AUD
```

**One audit cycle, in order.** The Lambda wakes any snoozed findings whose timer has expired and flips them back to open. It snapshots the set of currently-active findings. It runs every rule against freshly-fetched cloud state. It upserts each result with conditional writes (so a scheduled run and a manual trigger can't corrupt each other). It diffs the results against the pre-run snapshot to label findings as newly-appeared versus resolved. Finally it alerts only on the new ones and posts a count of the resolved ones, and reconciles the summary aggregate if it has gone stale.

## Design decisions and tradeoffs

**Idempotent, atomic writes.** Problem: the hourly schedule and a manual `/audit/trigger` can run concurrently, and a read-then-write upsert would let them clobber each other's occurrence counts or double-alert. Decision: a three-phase conditional write. Phase 1 attempts a create gated on `attribute_not_exists(pk)`. Phase 2 (on a hit) does a status-gated update that bumps `last_seen`/`occurrence_count`. Phase 3 only overwrites when the existing item is `RESOLVED`, which is the regression case. Tradeoff: three round trips in the worst case instead of one, in exchange for correctness under concurrency with no locks.

**Sparse, write-sharded active index.** Problem: queries like "all open findings" shouldn't scan the table, but a GSI keyed on a status with ~3 values creates a hot partition where every open item lands on one key. Decision: the `active-pk-index` carries the key `STATUS#shard`, where `shard = crc32(pk) % N` (default 10), and the key is dropped entirely on resolve/exempt. So the index is both sparse (resolved history never bloats it) and spread across N partitions per status. Tradeoff: reads fan out across the shards and merge, and N is fixed at deploy (changing it needs a re-shard), in exchange for removing the single-partition write ceiling.

**Maintained summary aggregate.** Problem: the dashboard's headline counts (`GET /summary`) were a full table scan on every page load, so cost and latency grew with finding history. Decision: a single item in a small summary table holds flat counters (`total`, `status#OPEN`, `sev#HIGH`, `team#infra#OPEN`), and every lifecycle transition applies an atomic `ADD` delta to it, so the endpoint is one `GetItem`. Counters can drift, for example when TTL deletes an old resolved finding. So the auditor rebuilds the aggregate from a scan once it is older than `SUMMARY_REBUILD_HOURS` (default 24). Counter writes are best-effort, so a failed bump can never fail the lifecycle change it describes. Tradeoff: counts can be briefly off, bounded by the rebuild interval, in exchange for summary reads that don't grow with the table.

**Exact cursor pagination.** Problem: `GET /violations` capped at 500 with no way to fetch the rest, and the sharded active index makes a plain `LastEvaluatedKey` insufficient. Decision: an opaque cursor that records the shard and the resume key within it. Each DynamoDB call asks only for the number of items still needed, so the resume key is exact and nothing is read and then silently dropped. Tradeoff: a filtered page can take a few round trips to fill, because DynamoDB applies `Limit` before filters.

**Alert de-noising.** Problem: a CSPM that re-alerts every finding every hour trains people to ignore it. Decision: alerts fire only on findings that are net-new relative to the pre-run snapshot. Tradeoff: the alert path depends on the persisted store being correct, which is why the write path above is conditional rather than best-effort.

**Cross-account via STS assume-role.** Problem: covering an org. Decision: one central auditor account assumes a read-only role in each member account rather than deploying the whole stack everywhere. Tradeoff: a small amount of per-account setup (one role) against a single place to operate, patch, and pay for.

**Its own posture.** Secrets live in Secrets Manager and are read at cold start, never injected into Lambda environment variables. Deploys use GitHub OIDC with no static AWS keys. Both are called out here because this is a security tool, and holding it to the standard it enforces is part of the story.

## Security of the tool itself

- **Least-privilege IAM.** The auditor's execution role is read-only against the services it inspects; the cross-account role is read-only too.
- **Private dashboard origin.** The dashboard bucket blocks all public access; CloudFront reaches it through an Origin Access Control, so the bucket is never directly reachable.
- **Authenticated API.** Cognito JWT (validated for signature, issuer, and `token_use`) for the dashboard, plus a constant-time API-key path for machine-to-machine callers.
- **Signed Slack callbacks.** The interactivity endpoint verifies the Slack request signature and rejects anything outside a 5-minute replay window.
- **No silent failures.** Every Lambda and schedule has an SQS dead-letter queue, and a CloudWatch alarm fires to SNS the moment a message lands in it.

## Policy catalog

| ID | Service | Severity | Checks |
|---|---|---|---|
| S3_001 | S3 | CRITICAL | All four PublicAccessBlock settings enabled |
| S3_002 | S3 | HIGH | Default server-side encryption configured |
| S3_003 | S3 | MEDIUM | Versioning enabled |
| S3_004 | S3 | CRITICAL | Bucket policy does not grant `Principal: "*"` |
| IAM_001 | IAM | CRITICAL | Console users have an MFA device |
| IAM_002 | IAM | HIGH | Access keys rotated within 90 days |
| IAM_003 | IAM | HIGH | Account password policy meets complexity rules |
| IAM_004 | IAM | CRITICAL | Root account has MFA enabled |
| EC2_001 | EC2 | CRITICAL | No SG allows SSH (22) from 0.0.0.0/0 |
| EC2_002 | EC2 | CRITICAL | No SG allows RDP (3389) from 0.0.0.0/0 |
| EC2_003 | EC2 | CRITICAL | No SG allows all traffic from any source |
| EC2_004 | EC2 | MEDIUM | No SG allows HTTP (80) from 0.0.0.0/0 |
| CT_001 | CloudTrail | CRITICAL | A logging trail covers every audited region (multi-region and org trails count) |
| CT_002 | CloudTrail | HIGH | Trails have log file validation enabled |
| CT_003 | CloudTrail | MEDIUM | Trail logs are encrypted with a KMS key |
| RDS_001 | RDS | CRITICAL | Instance is not publicly accessible |
| RDS_002 | RDS | HIGH | Storage encryption at rest is enabled |
| RDS_003 | RDS | MEDIUM | Automated backups retained for at least 7 days (configurable) |
| KMS_001 | KMS | MEDIUM | Customer-managed symmetric keys have automatic rotation enabled |
| EBS_001 | EBS | HIGH | Volumes are encrypted |
| EBS_002 | EBS | MEDIUM | Region-level EBS encryption by default is enabled |
| EBS_003 | EBS | CRITICAL | Snapshots are not shared publicly |

Rules are declared in `policies.yaml`. Adding one is two steps: add the YAML entry (id, name, severity, `check`), then implement that `check` handler in the relevant auditor. The auditors follow a small strategy interface (`fetch_resources` + `evaluate`), so a new service is a new class, not a change to the engine.

```yaml
# policies.yaml
- id: S3_002
  name: "S3 default encryption required"
  severity: HIGH
  check: encryption_disabled
```

## Deployment

**Prerequisites:** an AWS account, the AWS SAM CLI, and Node 18+ for the dashboard build.

```bash
# 1. One-time per account: deploy the OIDC trust stack so CI can assume a deploy role
make bootstrap GITHUB_ORG=your-org-name

# 2. Build and deploy the application stack (guided the first time, saves samconfig.toml)
make deploy-guided SLACK_WEBHOOK_URL=https://hooks.slack.com/...

# 3. Build and publish the dashboard (reads API + Cognito config from stack outputs)
make dashboard-deploy
```

After the first deploy, populate the secret if you didn't pass it as a parameter, and set your scan targets:

```bash
aws secretsmanager put-secret-value \
  --secret-id /cloudshield/production/secrets \
  --secret-string '{"slack_webhook_url":"...","api_key":"...","slack_signing_secret":"..."}'
```

**Cross-account scanning.** This is the step people get stuck on, so it's spelled out. Each account you want scanned must host a read-only role that trusts the central account. Deploy `member-account-role.yaml` into every member account (a CloudFormation StackSet across the org is the clean way), then list the targets in the `AuditTargetAccounts` parameter:

```json
[
  {"account_id": "111122223333", "region": "us-east-1", "role_arn": "arn:aws:iam::111122223333:role/CloudShieldAuditRole"},
  {"account_id": "444455556666", "region": "eu-west-1", "role_arn": "arn:aws:iam::444455556666:role/CloudShieldAuditRole"}
]
```

With no targets set, the auditor scans its own account and region.

### CloudFormation parameters

| Parameter | Default | Purpose |
|---|---|---|
| `SlackWebhookUrl` | _(NoEcho)_ | Incoming webhook for Block Kit alerts. Seeds the secret on first deploy. |
| `ApiKey` | _(empty)_ | Pre-shared key for the `X-Api-Key` machine-to-machine path. |
| `SlackSigningSecret` | _(empty)_ | Verifies Slack interactivity callbacks. |
| `AuditTargetAccounts` | `[]` | JSON array of cross-account scan targets. |
| `DigestToEmail` | _(empty)_ | Enables the weekly SES digest to this address. |
| `DigestFromEmail` | `cloudshield-noreply@example.com` | Verified SES sender. |
| `AuditScheduleExpression` | `rate(1 hour)` | How often the auditor runs. |
| `Environment` | `production` | Suffix applied to all resource names. |

CI/CD: every push and PR runs lint, type-check, and the test suite. The deploy job is opt-in and stays skipped until you set the `AWS_DEPLOY_ROLE_ARN` repository variable (from `make bootstrap`) and the `SLACK_WEBHOOK_URL` secret, so a fresh clone shows green on the checks that don't need an AWS account. When enabled, a push to `main` deploys via OIDC with no static keys. See `.github/workflows/deploy.yml`.

## Local development and testing

```bash
pip install -r requirements-dev.txt
make test         # 192 tests, Moto-backed (no real AWS)
make lint         # ruff
make type-check   # mypy

python scripts/local_run.py   # simulate a full audit cycle (all 7 services) against mocked AWS

cd dashboard && npm install && npm run dev   # http://localhost:5173, demo data

make local-api                               # real API + auditor on http://localhost:8787 (Moto-backed)
make dashboard-dev-real                      # dashboard wired to it on http://localhost:5173
```

The dashboard runs against an in-memory mock API by default, so no backend is needed to explore it. The mock follows the real API's contract (filters, cursor paging, lifecycle rules, error codes) and derives every count from one dataset, so triaging a finding moves the numbers everywhere. `make local-api` instead serves the real API Lambda against a Moto-faked AWS, seeded by a real audit, for full-stack work. Auth is a no-op when the Cognito environment variables are unset, so the SPA loads straight to the dashboard locally.

**Dashboard behaviour worth knowing:**
- Triage (acknowledge, snooze 1/7/30 days, exempt with a required reason, reopen) is optimistic in feel but server-confirmed: the card animates out only after the API accepts the change, failures leave it untouched with an explanation, and actions on open findings can be undone from the toast.
- Filters, severity and search live in the URL, so a view can be shared or bookmarked; `/` focuses search.
- Lists page through the API cursor with infinite scroll; counts refresh every minute while the tab is visible, and lists reload after an audit finishes or on the refresh button, without flashing skeletons.
- Responsive down to phone width (navigation becomes a drawer), keyboard accessible (focus-trapped dialogs, arrow-key menus, visible focus), text meets WCAG AA contrast, and animations respect "reduce motion".

The suite is part of the trust story, not an afterthought. It covers the violation lifecycle (including the regression and exempted-survives-reaudit edge cases), the JWT verification branches (valid id/access tokens, expired, wrong client, wrong issuer, key rotation), the Secrets Manager loader and its env fallback, write-sharding behavior, the multi-account evaluator including assume-role failure isolation, every auditor's pass and fail cases (including CloudTrail shadow-trail coverage), the summary counters through each transition and after drift, and cursor pagination across every index path.

## Configuration reference

Secrets come from Secrets Manager (via `SECRETS_ARN`). Everything below is non-secret runtime config.

| Variable | Set on | Purpose |
|---|---|---|
| `VIOLATIONS_TABLE` | all | DynamoDB violation store |
| `AUDIT_LOG_TABLE` | all | Append-only lifecycle trail |
| `SUMMARY_TABLE` | all | Maintained `/summary` aggregate |
| `SUMMARY_REBUILD_HOURS` | auditor | Max age before the auditor reconciles the aggregate (default 24) |
| `SECRETS_ARN` | all | Secrets Manager secret to read at cold start |
| `SNS_TOPIC_ARN` | all | Alert + alarm fan-out topic |
| `DASHBOARD_URL` | all | CloudFront URL (Slack deep links, CORS allow-list) |
| `AUDIT_TARGETS` | auditor | JSON cross-account targets (mirrors the parameter) |
| `ACTIVE_PK_SHARDS` | auditor/api | Shard count for the active index (default 10, fixed at deploy) |
| `AUDITOR_FUNCTION_NAME` | api | Target for the async `/audit/trigger` invoke |
| `COGNITO_ISSUER`, `COGNITO_CLIENT_ID` | api | JWT validation |
| `DIGEST_TO_EMAIL`, `DIGEST_FROM_EMAIL` | digest | Weekly SES summary |

## Project layout

```
src/
  auditors/       strategy base + s3/ec2/iam/cloudtrail/rds/kms/ebs auditors
  engine/         evaluator.py: multi-account/region fan-out
  store/          violations.py (lifecycle, sharded writes, summary counters, cursors), audit_log.py
  config/         secrets.py: Secrets Manager loader, cold-start cached
  notifications/  slack.py (Block Kit) + digest.py (weekly SES)
  api/            handler.py: API Gateway Lambda (Cognito JWT + API key)
  handler.py      scheduled auditor entrypoint
dashboard/        React 18 + Vite + TypeScript + Tailwind + Recharts
  src/hooks/      useAuth.ts: Cognito PKCE flow, in-memory tokens
tests/            192 tests (Moto-backed)
policies.yaml             declarative rule set
template.yaml             SAM IaC (DynamoDB x3, Lambda, API GW, CloudFront, Cognito, SQS, Secrets)
member-account-role.yaml  read-only role for each scanned account
```

## API reference

Every endpoint accepts `X-Api-Key: <key>` or `Authorization: Bearer <cognito-jwt>`.

| Method | Path | Description |
|---|---|---|
| GET | `/violations` | One page, filters: `?status=&severity=&team=&limit=&cursor=`. Returns `next_cursor` (null on the last page) |
| GET | `/violations/{id}` | One violation by `violation_id` |
| GET | `/violations/{id}/history` | Lifecycle trail, newest first |
| PATCH | `/violations/{id}` | `{"action": "acknowledge"\|"snooze"\|"exempt"\|"reopen"}`. `reopen` returns 409 unless the finding is acknowledged, snoozed or exempted |
| GET | `/summary` | Aggregate counts by status, severity, team, plus `by_severity_status` (severity x status matrix), read from the maintained aggregate |
| GET | `/trend` | Daily active findings per severity, oldest first: `?days=` (default 14, max 90). Days with no audit run are omitted |
| POST | `/audit/trigger` | Queue an out-of-cycle run (async, 202) |
| POST | `/slack/interact` | Slack button callback (signature-verified) |

## Known limitations and roadmap

- The active index shards writes across a fixed N partitions per status. That raises the ceiling a long way past a single-partition design, but at extreme concurrent-active volume you would raise N (a re-shard) or move to a per-status counter table.
- Summary counts are maintained incrementally and reconciled every `SUMMARY_REBUILD_HOURS`. The reconcile is still a full scan, just once a day rather than once per page load. A lifecycle change that lands during a rebuild can be missed until the next one.
- Listing with no status filter, or with `RESOLVED`/`EXEMPTED`, pages through a filtered scan rather than an index.
- KMS findings are attributed to a team through the key's `team` tag. CloudTrail and account-level findings show as `untagged`.
- Trend history starts when this version is deployed: the auditor records one snapshot per day, so the Posture chart shows an empty state until there are two days of data.
- The lifecycle history records transitions (acknowledge, snooze, exempt, resolve, wake, reopen), not the initial detection, so a finding nobody has touched shows an empty history.
- Natural next rules: GuardDuty enabled, VPC flow logs, Lambda public URLs, ELB TLS policies. Each is an additive auditor.

## License

MIT. See [LICENSE](LICENSE).
