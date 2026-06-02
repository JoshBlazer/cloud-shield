.DEFAULT_GOAL := help

PYTHON  := python
PIP     := pip
SAM     := sam

# Passed in at deploy time: make deploy SLACK_WEBHOOK_URL=https://...
SLACK_WEBHOOK_URL ?= REPLACE_ME

.PHONY: help install lint format type-check test test-cov \
        validate build deploy-guided deploy logs destroy bootstrap clean

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

validate: ## Validate the SAM template
	$(SAM) validate --template template.yaml --lint

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

dashboard-dev: ## Run dashboard dev server (mock API)
	cd dashboard && npm run dev

dashboard-build: ## Build dashboard for production (set VITE_API_URL first)
	cd dashboard && VITE_USE_MOCK=false VITE_API_URL=$(API_ENDPOINT) npm run build

dashboard-deploy: dashboard-build ## Build and sync dashboard to S3
	@test -n "$(DASHBOARD_BUCKET)" || (echo "ERROR: DASHBOARD_BUCKET not set and could not read from stack"; exit 1)
	aws s3 sync dashboard/dist/ s3://$(DASHBOARD_BUCKET)/ --delete
	@echo "Dashboard deployed to s3://$(DASHBOARD_BUCKET)"

# ── Housekeeping ─────────────────────────────────────────────────────────────

clean: ## Remove build artefacts, caches, and coverage reports
	rm -rf .aws-sam/ htmlcov/ .coverage .pytest_cache/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
