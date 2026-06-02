#!/usr/bin/env bash
# Deploy the one-time OIDC trust-policy stack.
# Run this once per AWS account before the first GitHub Actions deploy.
#
# Usage:
#   ./scripts/bootstrap.sh <github-org> [github-repo] [branch]
#
# Example:
#   ./scripts/bootstrap.sh acme-corp cloudshield-auditor main
set -euo pipefail

GITHUB_ORG="${1:?Usage: $0 <github-org> [repo] [branch]}"
GITHUB_REPO="${2:-cloudshield-auditor}"
GITHUB_BRANCH="${3:-main}"
STACK_NAME="cloudshield-oidc-bootstrap"
REGION="${AWS_REGION:-us-east-1}"

echo "Deploying OIDC bootstrap stack..."
echo "  Account : $(aws sts get-caller-identity --query Account --output text)"
echo "  Region  : $REGION"
echo "  GitHub  : ${GITHUB_ORG}/${GITHUB_REPO} @ ${GITHUB_BRANCH}"
echo ""

aws cloudformation deploy \
  --stack-name   "$STACK_NAME" \
  --template-file oidc-bootstrap.yaml \
  --region       "$REGION" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOrg="$GITHUB_ORG" \
    GitHubRepo="$GITHUB_REPO" \
    GitHubBranch="$GITHUB_BRANCH"

ROLE_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region     "$REGION" \
  --query      "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" \
  --output     text)

echo ""
echo "Done. Add the following secret to your GitHub repo:"
echo ""
echo "  Name  : AWS_DEPLOY_ROLE_ARN"
echo "  Value : $ROLE_ARN"
echo ""
echo "Also add SLACK_WEBHOOK_URL as a repository secret, then push to '${GITHUB_BRANCH}' to trigger the first deploy."
