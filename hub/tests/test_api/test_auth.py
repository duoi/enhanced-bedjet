"""Tests for the optional API authentication layer.

Covers the bearer-token mechanism, the Cloudflare Access (JWT) mechanism, the
way they compose when both are enabled, and the WebSocket rejection path.
"""

import asyncio
import contextlib
import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from bedjet_hub import auth as auth_module
from bedjet_hub.api.server import create_app
from bedjet_hub.ble.const import OperatingMode
from bedjet_hub.ble.state import DeviceMetadata, DeviceState
from bedjet_hub.db.database import Database

TEAM_DOMAIN = "https://example-team.cloudflareaccess.com"
AUDIENCE = "example-aud-tag"

#: Every environment variable the auth layer reads. Cleared before each test so
#: the suite is hermetic regardless of the developer's shell.
AUTH_ENV_VARS = (
    "HUB_API_TOKEN",
    "HUB_API_TOKEN_WS_QUERY",
    "CF_ACCESS_TEAM_DOMAIN",
    "CF_ACCESS_AUD",
    "CF_ACCESS_ALLOWED_EMAILS",
    "CF_ACCESS_JWKS_TTL",
)


@pytest.fixture(autouse=True)
def clean_auth_env(monkeypatch):
    """Ensure no ambient auth configuration leaks into a test."""
    for name in AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@contextlib.contextmanager
def hub_client():
    """Build a TestClient wired to a mocked BLE manager and a scratch database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(db.initialize())

    manager = MagicMock()
    manager.is_connected = True
    for method in (
        "set_mode",
        "set_fan_speed",
        "set_temperature",
        "set_led",
        "set_muted",
        "sync_clock",
        "set_runtime",
        "activate_memory",
        "activate_biorhythm",
    ):
        setattr(manager, method, AsyncMock())
    manager.get_state.return_value = DeviceState(
        mode=OperatingMode.HEAT,
        current_temperature_c=36.5,
        target_temperature_c=38.0,
        ambient_temperature_c=22.0,
        fan_speed_percent=60,
        runtime_remaining_seconds=1800,
        maximum_runtime_seconds=14400,
        min_temperature_c=19.0,
        max_temperature_c=43.0,
        led_enabled=True,
        beeps_muted=False,
        dual_zone=False,
        units_setup=True,
        connection_test_passed=True,
    )
    manager.get_metadata.return_value = DeviceMetadata(
        address="AA:BB",
        name="BedJet",
        model="v3",
        firmware_version="1.2.3",
        memory_names=["Sleep", None, None],
        biorhythm_names=["Night", None, None],
    )

    app = create_app(ble_manager=manager, db=db)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        loop.run_until_complete(db.close())
        os.unlink(path)


# --------------------------------------------------------------------------- #
# Bearer token
# --------------------------------------------------------------------------- #


def test_no_auth_configured_allows_anonymous_access(monkeypatch):
    with hub_client() as client:
        assert client.get("/api/device").status_code == 200


def test_missing_token_is_rejected(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        response = client.get("/api/device")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_valid_token_is_accepted(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        response = client.get("/api/device", headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 200


def test_wrong_token_is_rejected(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        response = client.get("/api/device", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Bearer ",
        "Token s3cret",
        "s3cret",
        "Basic czNjcmV0",
    ],
)
def test_malformed_authorization_header_is_rejected(monkeypatch, header):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        response = client.get("/api/device", headers={"Authorization": header})
    assert response.status_code == 401


def test_scheme_match_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        response = client.get("/api/device", headers={"Authorization": "bearer s3cret"})
    assert response.status_code == 200


def test_write_endpoints_are_protected(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        response = client.post("/api/device/mode", json={"mode": "heat"})
    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_documentation_is_protected(monkeypatch, path):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_documentation_is_open_without_auth(monkeypatch, path):
    with hub_client() as client:
        assert client.get(path).status_code == 200


def test_unprotected_paths_are_not_blocked(monkeypatch):
    """Only the API surface is gated; unknown paths still 404 rather than 401."""
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        assert client.get("/").status_code == 404


def test_cors_preflight_is_not_blocked_by_auth(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        response = client.options(
            "/api/device",
            headers={
                "Origin": "http://localhost:8678",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8678"


def test_cors_headers_survive_authenticated_requests(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8678")
    with hub_client() as client:
        response = client.get(
            "/api/device",
            headers={"Authorization": "Bearer s3cret", "Origin": "http://localhost:8678"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8678"


def test_token_is_not_accepted_as_a_query_parameter_on_http(monkeypatch):
    """Query-string tokens are WebSocket-only, so they never land in HTTP logs."""
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        assert client.get("/api/device?token=s3cret").status_code == 401


def test_bearer_only_mode_ignores_a_valid_access_jwt(monkeypatch, rsa_key, monkeypatch_jwks):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    token = sign_token(rsa_key)
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Cloudflare Access (JWT)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def other_rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def sign_token(key, **overrides):
    """Encode a Cloudflare-Access-shaped JWT signed with ``key``."""
    now = int(time.time())
    claims = {
        "aud": [AUDIENCE],
        "email": "user@example.com",
        "exp": now + 3600,
        "iat": now,
        "nbf": now - 10,
        "iss": TEAM_DOMAIN,
        "type": "app",
    }
    claims.update(overrides)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return pyjwt.encode(claims, pem, algorithm="RS256", headers={"kid": "test-kid"})


@pytest.fixture
def monkeypatch_jwks(monkeypatch, rsa_key):
    """Replace the remote JWKS client so no test ever performs network I/O."""

    class _StubJWKClient:
        def __init__(self, uri=None, **kwargs):
            self.uri = uri
            self.kwargs = kwargs

        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=rsa_key.public_key())

    monkeypatch.setattr(auth_module, "PyJWKClient", _StubJWKClient)
    return _StubJWKClient


def access_env(monkeypatch, **overrides):
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", TEAM_DOMAIN)
    monkeypatch.setenv("CF_ACCESS_AUD", AUDIENCE)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)


def test_valid_access_jwt_is_accepted(monkeypatch, rsa_key, monkeypatch_jwks):
    access_env(monkeypatch)
    token = sign_token(rsa_key)
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 200


def test_missing_access_jwt_is_rejected(monkeypatch, monkeypatch_jwks):
    access_env(monkeypatch)
    with hub_client() as client:
        assert client.get("/api/device").status_code == 401


def test_expired_access_jwt_is_rejected(monkeypatch, rsa_key, monkeypatch_jwks):
    access_env(monkeypatch)
    token = sign_token(rsa_key, exp=int(time.time()) - 3600)
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


def test_access_jwt_with_wrong_audience_is_rejected(monkeypatch, rsa_key, monkeypatch_jwks):
    access_env(monkeypatch)
    token = sign_token(rsa_key, aud=["some-other-application"])
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


def test_access_jwt_with_wrong_issuer_is_rejected(monkeypatch, rsa_key, monkeypatch_jwks):
    access_env(monkeypatch)
    token = sign_token(rsa_key, iss="https://attacker.cloudflareaccess.com")
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


def test_access_jwt_signed_by_another_key_is_rejected(
    monkeypatch, other_rsa_key, monkeypatch_jwks
):
    access_env(monkeypatch)
    token = sign_token(other_rsa_key)
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c", "eyJhbGciOiJub25lIn0.e30."])
def test_malformed_access_jwt_is_rejected(monkeypatch, monkeypatch_jwks, token):
    access_env(monkeypatch)
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


def test_access_allowed_emails_accepts_a_listed_identity(
    monkeypatch, rsa_key, monkeypatch_jwks
):
    access_env(monkeypatch, CF_ACCESS_ALLOWED_EMAILS="User@Example.com,other@example.com")
    token = sign_token(rsa_key, email="user@example.com")
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 200


def test_access_allowed_emails_rejects_an_unlisted_identity(
    monkeypatch, rsa_key, monkeypatch_jwks
):
    access_env(monkeypatch, CF_ACCESS_ALLOWED_EMAILS="someone@example.com")
    token = sign_token(rsa_key, email="user@example.com")
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


def test_access_allowed_emails_rejects_a_token_without_an_email(
    monkeypatch, rsa_key, monkeypatch_jwks
):
    access_env(monkeypatch, CF_ACCESS_ALLOWED_EMAILS="user@example.com")
    token = sign_token(rsa_key, email=None)
    with hub_client() as client:
        response = client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


def test_access_only_mode_ignores_a_valid_bearer_token(monkeypatch, monkeypatch_jwks):
    access_env(monkeypatch)
    with hub_client() as client:
        response = client.get("/api/device", headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 401


def test_jwks_client_is_constructed_with_the_derived_certs_url(
    monkeypatch, rsa_key, monkeypatch_jwks
):
    access_env(monkeypatch, CF_ACCESS_JWKS_TTL="60")
    seen = {}

    class _RecordingClient:
        def __init__(self, uri=None, **kwargs):
            seen["uri"] = uri
            seen["kwargs"] = kwargs
            seen["instance"] = self

        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=rsa_key.public_key())

    monkeypatch.setattr(auth_module, "PyJWKClient", _RecordingClient)
    token = sign_token(rsa_key)
    with hub_client() as client:
        assert (
            client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token}).status_code
            == 200
        )
    assert seen["uri"] == f"{TEAM_DOMAIN}/cdn-cgi/access/certs"
    assert seen["kwargs"]["cache_keys"] is True
    assert seen["kwargs"]["lifespan"] == 60


# --------------------------------------------------------------------------- #
# Both mechanisms enabled
# --------------------------------------------------------------------------- #


def test_both_enabled_accepts_either_mechanism(
    monkeypatch, rsa_key, monkeypatch_jwks
):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    access_env(monkeypatch)
    token = sign_token(rsa_key)
    with hub_client() as client:
        assert client.get("/api/device", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        assert (
            client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token}).status_code
            == 200
        )


def test_both_enabled_still_rejects_unauthenticated(monkeypatch, monkeypatch_jwks):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    access_env(monkeypatch)
    with hub_client() as client:
        assert client.get("/api/device").status_code == 401


def test_both_enabled_rejects_a_bad_token_and_a_bad_jwt(
    monkeypatch, rsa_key, monkeypatch_jwks
):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    access_env(monkeypatch)
    token = sign_token(rsa_key, iss="https://attacker.cloudflareaccess.com")
    with hub_client() as client:
        assert client.get("/api/device", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert (
            client.get("/api/device", headers={"Cf-Access-Jwt-Assertion": token}).status_code
            == 401
        )


# --------------------------------------------------------------------------- #
# WebSockets
# --------------------------------------------------------------------------- #


def test_websocket_requires_a_token(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass


def test_websocket_accepts_a_bearer_header(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        with client.websocket_connect("/ws", headers={"Authorization": "Bearer s3cret"}) as ws:
            assert ws.receive_json()["type"] == "state"


def test_websocket_accepts_a_query_token(monkeypatch):
    """Browsers cannot set headers on a WebSocket handshake."""
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        with client.websocket_connect("/ws?token=s3cret") as ws:
            assert ws.receive_json()["type"] == "state"


def test_websocket_rejects_a_wrong_query_token(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?token=wrong"):
                pass


def test_websocket_query_token_can_be_disabled(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    monkeypatch.setenv("HUB_API_TOKEN_WS_QUERY", "false")
    with hub_client() as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?token=s3cret"):
                pass
        with client.websocket_connect("/ws", headers={"Authorization": "Bearer s3cret"}) as ws:
            assert ws.receive_json()["type"] == "state"


def test_websocket_rejection_closes_with_policy_violation(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/ws"):
                pass
    assert excinfo.value.code == auth_module.WEBSOCKET_POLICY_VIOLATION


def test_websocket_is_open_without_auth(monkeypatch):
    with hub_client() as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "state"


def test_websocket_accepts_an_access_jwt_header(monkeypatch, rsa_key, monkeypatch_jwks):
    access_env(monkeypatch)
    token = sign_token(rsa_key)
    with hub_client() as client:
        with client.websocket_connect(
            "/ws", headers={"Cf-Access-Jwt-Assertion": token}
        ) as ws:
            assert ws.receive_json()["type"] == "state"


def test_websocket_rejects_an_invalid_access_jwt(monkeypatch, rsa_key, monkeypatch_jwks):
    from starlette.websockets import WebSocketDisconnect

    access_env(monkeypatch)
    token = sign_token(rsa_key, exp=int(time.time()) - 60)
    with hub_client() as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"Cf-Access-Jwt-Assertion": token}):
                pass


# --------------------------------------------------------------------------- #
# Startup warnings
# --------------------------------------------------------------------------- #


def test_unauthenticated_startup_logs_a_warning(monkeypatch, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.api.server"):
        with hub_client():
            pass
    assert any("unauthenticated" in record.message.lower() for record in caplog.records)


def test_wildcard_cors_with_auth_logs_a_warning(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with caplog.at_level(logging.WARNING, logger="bedjet_hub.api.server"):
        with hub_client():
            pass
    assert any("csrf" in record.message.lower() for record in caplog.records)


def test_wildcard_cors_without_auth_does_not_warn_about_csrf(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("CORS_ORIGINS", "*")
    with caplog.at_level(logging.WARNING, logger="bedjet_hub.api.server"):
        with hub_client():
            pass
    assert not any("csrf" in record.message.lower() for record in caplog.records)


# --------------------------------------------------------------------------- #
# Hardening: hostile input must never produce a 500
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw_token",
    [b"\xfc", b"\xc3\xbc", b"\xe2\x98\x83", b"\xf0\x9d\x94\xa5", b"s3cret\xe9"],
    ids=["latin1-u", "utf8-u", "snowman", "math-bold", "ascii-plus-e9"],
)
def test_non_ascii_bearer_token_is_rejected_and_never_500s(monkeypatch, raw_token):
    """``secrets.compare_digest`` raises TypeError on non-ASCII str input.

    An unauthenticated caller must not be able to turn that into a 500. The
    header is sent as raw bytes because that is what a real client puts on the
    wire; the server decodes them as latin-1, yielding a non-ASCII str.
    """
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        response = client.get("/api/device", headers={"Authorization": b"Bearer " + raw_token})
    assert response.status_code == 401


def test_non_ascii_ws_query_token_is_rejected_and_never_500s(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?token=ünïcödé"):
                pass


def test_token_is_still_accepted_after_a_non_ascii_attempt(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        assert client.get("/api/device", headers={"Authorization": b"Bearer \xfc"}).status_code == 401
        assert client.get("/api/device", headers={"Authorization": "Bearer s3cret"}).status_code == 200


# --------------------------------------------------------------------------- #
# Path normalisation: the gate must be at least as strict as the router
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/api/",
        "/api/device",
        "/api/device/",
        "/api//device",
        "/ws",
        "/ws/",
        "/docs",
        "/docs/",
        "/redoc",
        "/openapi.json",
        # Variants a router might normalise differently from a naive prefix check
        "/./api/device",
        "/api/./device",
        "/api/../api/device",
        "/%61pi/device",
    ],
)
def test_is_protected_path_covers_path_variants(path):
    assert auth_module.is_protected_path(path) is True


@pytest.mark.parametrize(
    "path",
    ["/", "/index.html", "/assets/index-abc.js", "/wsfoo", "/apix", "/notapi/device", "/apiary"],
)
def test_is_protected_path_leaves_everything_else_open(path):
    assert auth_module.is_protected_path(path) is False


def test_repeated_leading_slashes_cannot_reach_an_api_route(monkeypatch):
    """Regression guard: whatever the router does with '//', the gate must hold."""
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    with hub_client() as client:
        assert client.get("//api/device").status_code in (401, 404)


def test_insecure_team_domain_logs_a_warning(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "http://idp.internal.example")
    monkeypatch.setenv("CF_ACCESS_AUD", "aud-tag")
    with caplog.at_level(logging.WARNING, logger="bedjet_hub.auth"):
        with hub_client():
            pass
    assert any("https" in record.message.lower() for record in caplog.records)


def test_https_team_domain_does_not_warn(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "https://team.cloudflareaccess.com")
    monkeypatch.setenv("CF_ACCESS_AUD", "aud-tag")
    with caplog.at_level(logging.WARNING, logger="bedjet_hub.auth"):
        with hub_client():
            pass
    assert not any("https" in record.message.lower() for record in caplog.records)
