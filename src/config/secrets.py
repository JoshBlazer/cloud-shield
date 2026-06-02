"""
Central secret access.

In AWS, secrets live in Secrets Manager and are fetched once at cold start, then
cached at module scope for the life of the warm Lambda container. They are NOT
injected into Lambda environment variables, so they don't show up in the console's
function configuration.

For local dev and tests (no SECRETS_ARN set), values fall back to individual
environment variables. The fallback path is not cached, so monkeypatched env vars
are always honored by tests.
"""

import json
import os
from typing import Any

import boto3
import structlog

log = structlog.get_logger()

# Logical secret key -> env-var name used as the local/dev fallback
_ENV_FALLBACK = {
    "slack_webhook_url":    "SLACK_WEBHOOK_URL",
    "api_key":              "API_KEY",
    "slack_signing_secret": "SLACK_SIGNING_SECRET",
}

# Cached only when loaded from Secrets Manager (warm-container reuse)
_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache

    arn = os.environ.get("SECRETS_ARN", "")
    if arn:
        try:
            client = boto3.client("secretsmanager")
            raw    = client.get_secret_value(SecretId=arn)["SecretString"]
            _cache = json.loads(raw)
            log.info("secrets.loaded", source="secretsmanager")
            return _cache
        except Exception as exc:  # noqa: BLE001
            log.error("secrets.load_failed", error=str(exc))
            # fall through to env fallback rather than hard-failing the request

    # Local/dev/test fallback — re-read each call so tests see fresh env
    return {key: os.environ.get(env, "") for key, env in _ENV_FALLBACK.items()}


def get_secret(key: str) -> str:
    """Return one secret value by logical key, or '' if unset."""
    return _load().get(key, "")


def reset_cache() -> None:
    """Test helper — drop the cached Secrets Manager payload."""
    global _cache
    _cache = None


def __getattr__(name: str) -> Any:  # pragma: no cover - convenience only
    raise AttributeError(name)
