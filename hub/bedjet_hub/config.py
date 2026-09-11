"""Hub configuration loaded from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

#: Request header carrying the signed identity token from a trusted identity
#: proxy. Cloudflare Access uses this name for its application token.
DEFAULT_JWT_HEADER = "cf-access-jwt-assertion"

#: Default lifetime, in seconds, of a cached set of JWT signing keys.
#: Cloudflare Access rotates its signing key every six weeks and keeps the
#: previous key valid for seven days, so any cache this side of that window
#: cannot serve a stale key for long enough to matter.
DEFAULT_JWKS_TTL = 1800

#: Path appended to the team domain to fetch the current signing keys.
JWKS_PATH = "/cdn-cgi/access/certs"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def _env_bool(source: Mapping[str, str], name: str, default: bool) -> bool:
    """Read a boolean flag, falling back to ``default`` when unset or unclear."""
    raw = (source.get(name) or "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return default


def _env_positive_int(source: Mapping[str, str], name: str, default: int) -> int:
    """Read a positive integer, falling back to ``default`` when unusable."""
    raw = (source.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_list(source: Mapping[str, str], name: str) -> list[str]:
    """Read a comma-separated list, discarding blank entries."""
    raw = source.get(name) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_team_domain(raw: str | None) -> str | None:
    """Normalize a team domain to a bare ``https://`` origin, or ``None``."""
    value = (raw or "").strip().rstrip("/")
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


class Config:
    """Runtime configuration sourced from environment variables.

    Read at instantiation rather than import time so that a caller (including
    a test harness) can supply a specific environment.

    Attributes:
        bedjet_address: BLE MAC address of the BedJet device. Empty string
            triggers auto-scan.
        hub_host: Network interface to bind the HTTP/WS server on.
        hub_port: TCP port for the hub server.
        db_path: Filesystem path for the SQLite database.
        cors_origins: Origins permitted to make browser requests to the API.
    """

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        source = os.environ if env is None else env
        self.bedjet_address: str = source.get("BEDJET_ADDRESS", "")
        self.hub_host: str = source.get("HUB_HOST", "0.0.0.0")
        self.hub_port: int = int(source.get("HUB_PORT", "8265"))
        self.db_path: str = source.get("DB_PATH", "data/bedjet.db")
        self.cors_origins: list[str] = [
            origin.strip()
            for origin in source.get(
                "CORS_ORIGINS", "http://localhost:8678,http://localhost:5173"
            ).split(",")
            if origin.strip()
        ]


@dataclass(frozen=True)
class AuthConfig:
    """Optional API authentication, sourced from environment variables.

    Two mechanisms are supported and both are off by default:

    * a shared bearer token (``HUB_API_TOKEN``), and
    * a signed JWT issued by an identity proxy such as Cloudflare Access
      (``CF_ACCESS_TEAM_DOMAIN`` + ``CF_ACCESS_AUD``).

    Enabling either one — or both — makes the protected API paths
    deny-by-default. When both are configured a request is accepted if it
    satisfies *at least one* of them, so a browser can authenticate through the
    identity proxy while a script authenticates with the bearer token.

    Attributes:
        token: Shared bearer token, or ``None`` when bearer auth is disabled.
        token_ws_query: Whether ``/ws`` may accept the token as a ``token``
            query parameter. Browsers cannot set headers on a WebSocket
            handshake, so this is what makes token auth usable from the web UI.
            It is off whenever the token itself is unset.
        jwt_team_domain: Team domain origin used as the expected JWT issuer.
        jwt_audience: Application Audience (AUD) tag the JWT must be minted for.
        jwt_allowed_emails: When non-empty, the token's ``email`` claim must
            match one of these addresses.
        jwt_header: Request header carrying the signed token.
        jwks_ttl: Seconds to cache fetched signing keys.
    """

    token: str | None = None
    token_ws_query: bool = True
    jwt_team_domain: str | None = None
    jwt_audience: str | None = None
    jwt_allowed_emails: frozenset[str] = frozenset()
    jwt_header: str = DEFAULT_JWT_HEADER
    jwks_ttl: int = DEFAULT_JWKS_TTL

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AuthConfig":
        """Build an :class:`AuthConfig` from ``env`` (default: the process env)."""
        source = os.environ if env is None else env
        return cls(
            token=(source.get("HUB_API_TOKEN") or "").strip() or None,
            token_ws_query=_env_bool(source, "HUB_API_TOKEN_WS_QUERY", True),
            jwt_team_domain=_normalize_team_domain(source.get("CF_ACCESS_TEAM_DOMAIN")),
            jwt_audience=(source.get("CF_ACCESS_AUD") or "").strip() or None,
            jwt_allowed_emails=frozenset(
                email.lower() for email in _env_list(source, "CF_ACCESS_ALLOWED_EMAILS")
            ),
            jwks_ttl=_env_positive_int(source, "CF_ACCESS_JWKS_TTL", DEFAULT_JWKS_TTL),
        )

    @property
    def bearer_enabled(self) -> bool:
        """True when a bearer token is configured."""
        return bool(self.token)

    @property
    def jwt_enabled(self) -> bool:
        """True when both halves of the identity-proxy configuration are present."""
        return bool(self.jwt_team_domain and self.jwt_audience)

    @property
    def enabled(self) -> bool:
        """True when at least one authentication mechanism is configured."""
        return self.bearer_enabled or self.jwt_enabled

    @property
    def issuer(self) -> str | None:
        """Expected ``iss`` claim, derived from the team domain."""
        return self.jwt_team_domain

    @property
    def jwks_url(self) -> str | None:
        """Signing-key endpoint, derived from the team domain."""
        if not self.jwt_team_domain:
            return None
        return f"{self.jwt_team_domain}{JWKS_PATH}"
