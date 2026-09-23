.DEFAULT_GOAL := help

PYTHON  := python
PIP     := pip
SAM     := sam

# Passed in at deploy time: make deploy SLACK_WEBHOOK_URL=https://...
SLACK_WEBHOOK_URL ?= REPLACE_ME

.PHONY: help install lint format type-check test test-cov \
        validate build deploy-guided deploy logs destroy bootstrap clean \
        dashboard-dev local-api dashboard-dev-real validate-offline release member-role

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Dependencies ────────────────────────────────────────────────────────────

install: ## Install all dev dependencies
	$(PIP) install -r requirements-dev.txt

# ── Code quality ─────────────────────────────────────────────────────────────

lint: ## Ruff lint check (no auto-fix)
	$(PYTHON) -m ruff check src/ tests/

format: ## Auto-fix lint issues and format code
	$(PYTHON) -m ruff check src/ tests/ --fix
	$(PYTHON) -m ruff format src/ tests/

type-check: ## Mypy static type check
	$(PYTHON) -m mypy src/ --ignore-missing-imports

# ── Tests ─────────────────────────────────────────────────────────────────

test: ## Run test suite
	$(PYTHON) -m pytest tests/ -v

test-cov: ## Run tests with HTML + terminal coverage report
	$(PYTHON) -m pytest tests/ -v \
	  --cov=src \
	  --cov-report=term-missing \
	  --cov-report=html:htmlcov

# ── SAM / AWS ─────────────────────────────────────────────────────────────

validate: ## Validate the SAM template (needs the SAM CLI and AWS credentials)
	$(SAM) validate --template template.yaml --lint

validate-offline: ## Validate all templates offline: SAM transform + cfn-lint (no AWS needed)
	$(PYTHON) scripts/validate_templates.py

build: ## Build the Lambda deployment package
	$(SAM) build

deploy-guided: build ## First-time interactive deploy — generates samconfig.toml answers
	$(SAM) deploy --guided \
	  --parameter-overrides \
	    Environment=production \
	    SlackWebhookUrl=$(SLACK_WEBHOOK_URL)

deploy: build ## Deploy using saved samconfig.toml (CI / subsequent runs)
	$(SAM) deploy \
	  --parameter-overrides \
	    Environment=production \
	    SlackWebhookUrl=$(SLACK_WEBHOOK_URL)

logs: ## Tail Lambda CloudWatch logs in real time
	$(SAM) logs --tail

destroy: ## Permanently delete the CloudFormation stack and all resources
	@echo "WARNING: this deletes ALL CloudShield infrastructure. Ctrl+C within 5 s to abort."
	@sleep 5
	$(SAM) delete

# ── OIDC bootstrap ──────────────────────────────────────────────────────────

bootstrap: ## Deploy the OIDC trust-policy stack (run once per AWS account)
	@test -n "$(GITHUB_ORG)" || (echo "ERROR: set GITHUB_ORG=<your-org>"; exit 1)
	./scripts/bootstrap.sh $(GITHUB_ORG)

# ── Dashboard ─────────────────────────────────────────────────────────────────

DASHBOARD_BUCKET ?= $(shell aws cloudformation describe-stacks \
	--stack-name cloudshield-auditor-production \
	--query "Stacks[0].Outputs[?OutputKey=='DashboardBucketName'].OutputValue" \
	--output text 2>/dev/null)

API_ENDPOINT ?= $(shell aws cloudformation describe-stacks \
	--stack-name cloudshield-auditor-production \
	--query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
	--output text 2>/dev/null)

COGNITO_DOMAIN ?= $(shell aws cloudformation describe-stacks \
	--stack-name cloudshield-auditor-production \
	--query "Stacks[0].Outputs[?OutputKey=='CognitoDomain'].OutputValue" \
	--output text 2>/dev/null)

COGNITO_CLIENT_ID ?= $(shell aws cloudformation describe-stacks \
	--stack-name cloudshield-auditor-production \
	--query "Stacks[0].Outputs[?OutputKey=='CognitoClientId'].OutputValue" \
	--output text 2>/dev/null)

DASHBOARD_URL ?= $(shell aws cloudformation describe-stacks \
	--stack-name cloudshield-auditor-production \
	--query "Stacks[0].Outputs[?OutputKey=='DashboardUrl'].OutputValue" \
	--output text 2>/dev/null)

dashboard-dev: ## Run dashboard dev server (mock API)
	cd dashboard && npm run dev

local-api: ## Serve the real API + auditor locally on :8787 against Moto (no AWS needed)
	$(PYTHON) scripts/local_api.py

dashboard-dev-real: ## Run dashboard dev server against `make local-api`
	cd dashboard && VITE_USE_MOCK=false VITE_API_URL=http://localhost:8787 npm run dev

dashboard-build: ## Build dashboard for production (pulls API + Cognito config from stack outputs)
	cd dashboard && \
	  VITE_USE_MOCK=false \
	  VITE_API_URL=$(API_ENDPOINT) \
	  VITE_COGNITO_DOMAIN=$(COGNITO_DOMAIN) \
	  VITE_COGNITO_CLIENT_ID=$(COGNITO_CLIENT_ID) \
	  VITE_APP_URL=$(DASHBOARD_URL) \
	  npm run build

DASHBOARD_DISTRIBUTION ?= $(shell aws cloudformation describe-stacks 	--stack-name cloudshield-auditor-production 	--query "Stacks[0].Outputs[?OutputKey=='DashboardDistributionId'].OutputValue" 	--output text 2>/dev/null)

# Order matters. Content-hashed assets go up first with a long immutable cache and
# are never deleted here, so browsers still holding the previous index.html keep
# working. index.html goes last with no-cache, then CloudFront is invalidated so the
# new version is served at once (the CachingOptimized policy would otherwise keep
# the old index.html for up to a day — pointing at assets that no longer exist).
dashboard-deploy: dashboard-build ## Build and publish the dashboard to S3 + CloudFront
	@test -n "$(DASHBOARD_BUCKET)" || (echo "ERROR: DASHBOARD_BUCKET not set and could not read from stack"; exit 1)
	aws s3 sync dashboard/dist/assets/ s3://$(DASHBOARD_BUCKET)/assets/ 	  --cache-control "public, max-age=31536000, immutable"
	aws s3 sync dashboard/dist/ s3://$(DASHBOARD_BUCKET)/ --exclude "assets/*" --exclude "index.html" 	  --cache-control "public, max-age=300"
	aws s3 cp dashboard/dist/index.html s3://$(DASHBOARD_BUCKET)/index.html 	  --cache-control "no-cache" --content-type "text/html; charset=utf-8"
	@if [ -n "$(DASHBOARD_DISTRIBUTION)" ]; then 	  aws cloudfront create-invalidation --distribution-id $(DASHBOARD_DISTRIBUTION) --paths "/index.html" "/" >/dev/null && 	  echo "Invalidated /index.html on $(DASHBOARD_DISTRIBUTION)"; 	else echo "WARNING: DashboardDistributionId output not found; skipped CloudFront invalidation"; fi
	@echo "Dashboard deployed to s3://$(DASHBOARD_BUCKET)"

# The dashboard's Undo/Reopen, trend chart and severity breakdown need the new API,
# so the backend always goes first. The second step runs in a fresh make so the
# stack outputs (bucket, API URL, Cognito) are read after the deploy, not before.
release: deploy ## Deploy backend, then dashboard, in that order
	$(MAKE) dashboard-deploy

# Run with credentials for the MEMBER account being scanned. For an AWS
# Organization, update the StackSet instead (see README "Cross-account scanning").
member-role: ## Deploy/update the read-only CloudShieldAuditRole in the current account
	@test -n "$(CENTRAL_ACCOUNT_ID)" || (echo "ERROR: set CENTRAL_ACCOUNT_ID=<12-digit central account id>"; exit 1)
	aws cloudformation deploy 	  --template-file member-account-role.yaml 	  --stack-name cloudshield-member-role 	  --capabilities CAPABILITY_NAMED_IAM 	  --no-fail-on-empty-changeset 	  --parameter-overrides CentralAccountId=$(CENTRAL_ACCOUNT_ID) $(if $(EXTERNAL_ID),ExternalId=$(EXTERNAL_ID),)

# ── Housekeeping ─────────────────────────────────────────────────────────────

clean: ## Remove build artefacts, caches, and coverage reports
	rm -rf .aws-sam/ htmlcov/ .coverage .pytest_cache/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
