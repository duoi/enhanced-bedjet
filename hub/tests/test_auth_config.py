"""Tests for environment-driven authentication configuration."""

import dataclasses

import pytest

from bedjet_hub.config import DEFAULT_JWKS_TTL, AuthConfig


def test_defaults_to_disabled():
    config = AuthConfig.from_env({})
    assert config.enabled is False
    assert config.bearer_enabled is False
    assert config.jwt_enabled is False
    assert config.token is None
    assert config.token_ws_query is True
    assert config.jwks_ttl == DEFAULT_JWKS_TTL


def test_bearer_token_enables_bearer_auth():
    config = AuthConfig.from_env({"HUB_API_TOKEN": "s3cret"})
    assert config.bearer_enabled is True
    assert config.enabled is True
    assert config.token == "s3cret"


def test_blank_bearer_token_is_treated_as_absent():
    config = AuthConfig.from_env({"HUB_API_TOKEN": "   "})
    assert config.bearer_enabled is False
    assert config.enabled is False


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE", "No"])
def test_ws_query_token_can_be_disabled(value):
    config = AuthConfig.from_env({"HUB_API_TOKEN": "s3cret", "HUB_API_TOKEN_WS_QUERY": value})
    assert config.token_ws_query is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "anything-else"])
def test_ws_query_token_defaults_to_enabled(value):
    config = AuthConfig.from_env({"HUB_API_TOKEN": "s3cret", "HUB_API_TOKEN_WS_QUERY": value})
    assert config.token_ws_query is True


def test_team_domain_alone_does_not_enable_jwt():
    config = AuthConfig.from_env({"CF_ACCESS_TEAM_DOMAIN": "https://team.cloudflareaccess.com"})
    assert config.jwt_enabled is False
    assert config.enabled is False


def test_audience_alone_does_not_enable_jwt():
    config = AuthConfig.from_env({"CF_ACCESS_AUD": "aud-tag"})
    assert config.jwt_enabled is False
    assert config.enabled is False


def test_team_domain_and_audience_enable_jwt():
    config = AuthConfig.from_env(
        {
            "CF_ACCESS_TEAM_DOMAIN": "https://team.cloudflareaccess.com",
            "CF_ACCESS_AUD": "aud-tag",
        }
    )
    assert config.jwt_enabled is True
    assert config.enabled is True
    assert config.issuer == "https://team.cloudflareaccess.com"
    assert config.jwks_url == "https://team.cloudflareaccess.com/cdn-cgi/access/certs"


@pytest.mark.parametrize(
    "raw",
    [
        "https://team.cloudflareaccess.com",
        "https://team.cloudflareaccess.com/",
        "team.cloudflareaccess.com",
        "team.cloudflareaccess.com/",
        "  https://team.cloudflareaccess.com/  ",
    ],
)
def test_team_domain_is_normalized(raw):
    config = AuthConfig.from_env({"CF_ACCESS_TEAM_DOMAIN": raw, "CF_ACCESS_AUD": "aud-tag"})
    assert config.issuer == "https://team.cloudflareaccess.com"
    assert config.jwks_url == "https://team.cloudflareaccess.com/cdn-cgi/access/certs"


def test_blank_team_domain_is_treated_as_absent():
    config = AuthConfig.from_env({"CF_ACCESS_TEAM_DOMAIN": "  ", "CF_ACCESS_AUD": "aud-tag"})
    assert config.jwt_enabled is False


@pytest.mark.parametrize("raw", ["", "  ", ","])
def test_empty_email_allowlist_is_permissive_by_default(raw):
    config = AuthConfig.from_env({"CF_ACCESS_ALLOWED_EMAILS": raw})
    assert config.jwt_allowed_emails == frozenset()


def test_email_allowlist_is_normalized():
    config = AuthConfig.from_env(
        {"CF_ACCESS_ALLOWED_EMAILS": " A@Example.com , b@example.com ,, "}
    )
    assert config.jwt_allowed_emails == frozenset({"a@example.com", "b@example.com"})


def test_jwks_ttl_is_configurable():
    config = AuthConfig.from_env({"CF_ACCESS_JWKS_TTL": "120"})
    assert config.jwks_ttl == 120


@pytest.mark.parametrize("value", ["", "abc", "0", "-5", "1.5"])
def test_invalid_jwks_ttl_falls_back_to_the_default(value):
    config = AuthConfig.from_env({"CF_ACCESS_JWKS_TTL": value})
    assert config.jwks_ttl == DEFAULT_JWKS_TTL


def test_from_env_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "from-os-environ")
    assert AuthConfig.from_env().token == "from-os-environ"


def test_config_is_immutable():
    config = AuthConfig.from_env({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.token = "nope"
