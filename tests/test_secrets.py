"""Tests for the Secrets Manager loader and its env-var fallback."""

import json

import boto3
import pytest
from moto import mock_aws
from src.config import secrets


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts with a clean module cache."""
    secrets.reset_cache()
    yield
    secrets.reset_cache()


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID",     "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION",    "us-east-1")


class TestSecretsManagerPath:
    def test_reads_from_secrets_manager(self, aws_credentials, monkeypatch):
        with mock_aws():
            sm  = boto3.client("secretsmanager", region_name="us-east-1")
            arn = sm.create_secret(
                Name="/cloudshield/test/secrets",
                SecretString=json.dumps({
                    "slack_webhook_url":    "https://hooks.slack.com/xyz",
                    "api_key":              "supersecret",
                    "slack_signing_secret": "signingsecret",
                }),
            )["ARN"]
            monkeypatch.setenv("SECRETS_ARN", arn)

            assert secrets.get_secret("api_key") == "supersecret"
            assert secrets.get_secret("slack_webhook_url") == "https://hooks.slack.com/xyz"
            assert secrets.get_secret("slack_signing_secret") == "signingsecret"

    def test_missing_key_returns_empty(self, aws_credentials, monkeypatch):
        with mock_aws():
            sm  = boto3.client("secretsmanager", region_name="us-east-1")
            arn = sm.create_secret(
                Name="/cloudshield/test/secrets2",
                SecretString=json.dumps({"api_key": "k"}),
            )["ARN"]
            monkeypatch.setenv("SECRETS_ARN", arn)
            assert secrets.get_secret("does_not_exist") == ""

    def test_caches_after_first_load(self, aws_credentials, monkeypatch):
        with mock_aws():
            sm  = boto3.client("secretsmanager", region_name="us-east-1")
            arn = sm.create_secret(
                Name="/cloudshield/test/secrets3",
                SecretString=json.dumps({"api_key": "first"}),
            )["ARN"]
            monkeypatch.setenv("SECRETS_ARN", arn)

            assert secrets.get_secret("api_key") == "first"
            # Mutate the secret in place — cached value should NOT change
            sm.put_secret_value(SecretId=arn, SecretString=json.dumps({"api_key": "second"}))
            assert secrets.get_secret("api_key") == "first"
            # After an explicit reset, the new value is picked up
            secrets.reset_cache()
            assert secrets.get_secret("api_key") == "second"


class TestEnvFallback:
    def test_falls_back_to_env_when_no_arn(self, monkeypatch):
        monkeypatch.delenv("SECRETS_ARN", raising=False)
        monkeypatch.setenv("API_KEY", "from-env")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://env.example")
        assert secrets.get_secret("api_key") == "from-env"
        assert secrets.get_secret("slack_webhook_url") == "https://env.example"

    def test_env_fallback_not_cached(self, monkeypatch):
        monkeypatch.delenv("SECRETS_ARN", raising=False)
        monkeypatch.setenv("API_KEY", "v1")
        assert secrets.get_secret("api_key") == "v1"
        # Env fallback path re-reads each call, so monkeypatched changes are seen
        monkeypatch.setenv("API_KEY", "v2")
        assert secrets.get_secret("api_key") == "v2"

    def test_unset_returns_empty(self, monkeypatch):
        monkeypatch.delenv("SECRETS_ARN", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        assert secrets.get_secret("api_key") == ""

    def test_load_failure_falls_back_to_env(self, aws_credentials, monkeypatch):
        # ARN points at a nonexistent secret → get_secret_value raises → env fallback
        monkeypatch.setenv("SECRETS_ARN", "arn:aws:secretsmanager:us-east-1:000000000000:secret:nope")
        monkeypatch.setenv("API_KEY", "fallback-key")
        with mock_aws():
            assert secrets.get_secret("api_key") == "fallback-key"
