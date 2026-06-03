"""Unit tests for the JWT verification gate (_verify_jwt) and JWKS refresh."""

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt
from src.api import handler

# Capture the real _load_jwks before the autouse fixture stubs it out
_REAL_LOAD_JWKS = handler._load_jwks

ISSUER     = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TESTPOOL"
CLIENT_ID  = "test-client-id-123"
KID        = "test-kid-1"


# ── Key material (generated once for the module) ────────────────────────────────

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

_PRIV_PEM = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()

_PUB_PEM = _private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()


def _jwks(kid: str = KID) -> dict:
    d = jwk.construct(_PUB_PEM, "RS256").to_dict()
    # jose returns bytes for n/e in some versions — normalize to str for JSON-like dict
    for f in ("n", "e"):
        if isinstance(d.get(f), bytes):
            d[f] = d[f].decode()
    d.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return {"keys": [d]}


def _sign(claims: dict, kid: str = KID) -> str:
    return jwt.encode(claims, _PRIV_PEM, algorithm="RS256", headers={"kid": kid})


def _id_claims(**over) -> dict:
    base = {
        "iss": ISSUER, "aud": CLIENT_ID, "token_use": "id",
        "sub": "user-1", "iat": int(time.time()), "exp": int(time.time()) + 3600,
    }
    base.update(over)
    return base


def _access_claims(**over) -> dict:
    base = {
        "iss": ISSUER, "client_id": CLIENT_ID, "token_use": "access",
        "sub": "user-1", "iat": int(time.time()), "exp": int(time.time()) + 3600,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _wire_cognito(monkeypatch):
    """Point the handler at the test pool and serve our local JWKS."""
    monkeypatch.setattr(handler, "_COGNITO_ISSUER", ISSUER)
    monkeypatch.setattr(handler, "_COGNITO_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(handler, "_load_jwks", lambda force=False: _jwks())
    yield


class TestValidTokens:
    def test_valid_id_token(self):
        assert handler._verify_jwt(_sign(_id_claims())) is True

    def test_valid_access_token(self):
        assert handler._verify_jwt(_sign(_access_claims())) is True


class TestRejectedTokens:
    def test_expired_token(self):
        expired = _id_claims(exp=int(time.time()) - 10, iat=int(time.time()) - 3600)
        assert handler._verify_jwt(_sign(expired)) is False

    def test_wrong_client_id_on_id_token(self):
        assert handler._verify_jwt(_sign(_id_claims(aud="some-other-client"))) is False

    def test_wrong_client_id_on_access_token(self):
        assert handler._verify_jwt(_sign(_access_claims(client_id="rogue"))) is False

    def test_wrong_issuer(self):
        assert handler._verify_jwt(_sign(_id_claims(iss="https://evil.example.com"))) is False

    def test_unknown_token_use(self):
        assert handler._verify_jwt(_sign(_id_claims(token_use="confirmation"))) is False

    def test_garbage_token(self):
        assert handler._verify_jwt("not.a.jwt") is False

    def test_token_signed_by_wrong_key(self):
        # A token signed by a different key must fail signature verification
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        forged = jwt.encode(_id_claims(), other_pem, algorithm="RS256", headers={"kid": KID})
        assert handler._verify_jwt(forged) is False


class TestDisabledAuth:
    def test_no_cognito_config_returns_false(self, monkeypatch):
        monkeypatch.setattr(handler, "_COGNITO_ISSUER", "")
        assert handler._verify_jwt(_sign(_id_claims())) is False


class TestJwksRotationRefresh:
    def test_unknown_kid_forces_refresh(self, monkeypatch):
        """Token signed with a rotated kid not in the stale cache should trigger a forced refresh."""
        calls = {"force": 0, "normal": 0}

        def fake_load(force=False):
            if force:
                calls["force"] += 1
                return _jwks(kid="new-kid")   # refreshed set contains the rotated key
            calls["normal"] += 1
            return _jwks(kid="stale-kid")     # cached set has the OLD key only

        monkeypatch.setattr(handler, "_load_jwks", fake_load)
        token = _sign(_id_claims(), kid="new-kid")
        assert handler._verify_jwt(token) is True
        assert calls["force"] == 1  # rotation triggered exactly one forced refetch


class TestJwksTtl:
    def test_ttl_expiry_triggers_refetch(self, monkeypatch):
        """_load_jwks should re-fetch once the TTL has elapsed."""
        fetches = {"n": 0}

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                fetches["n"] += 1
                return b'{"keys": []}'

        monkeypatch.setattr(handler, "_COGNITO_ISSUER", ISSUER)
        monkeypatch.setattr(handler, "_load_jwks", _REAL_LOAD_JWKS)  # undo autouse stub
        monkeypatch.setattr(handler, "_JWKS_CACHE", {})
        monkeypatch.setattr(handler, "_JWKS_FETCHED_AT", 0.0)
        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResp())

        handler._load_jwks()                       # cold → fetch #1
        handler._load_jwks()                       # within TTL → cached, no fetch
        assert fetches["n"] == 1

        # Age the cache past the TTL → next call refetches
        monkeypatch.setattr(handler, "_JWKS_FETCHED_AT", time.time() - handler._JWKS_TTL - 1)
        handler._load_jwks()
        assert fetches["n"] == 2
