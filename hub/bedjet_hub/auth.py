"""Optional authentication for the Hub API.

Two independent mechanisms are available, both configured through the
environment (see :class:`bedjet_hub.config.AuthConfig`):

* ``HUB_API_TOKEN`` — a shared bearer token, compared in constant time.
* ``CF_ACCESS_*`` — a signed JWT issued by an identity proxy such as Cloudflare
  Access, verified against the issuer's published signing keys.

Neither is enabled by default, which is appropriate only for a trusted LAN.
Configuring either one turns the API paths into deny-by-default; when both are
configured, satisfying either is sufficient.

This is deliberately a **pure ASGI** middleware: HTTP-scoped middleware
(``BaseHTTPMiddleware`` / ``@app.middleware("http")``) short-circuits on any
non-HTTP scope, so it would silently leave the ``/ws`` WebSocket unauthenticated.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from urllib.parse import unquote

from jwt import PyJWKClient
from jwt import decode as jwt_decode
from jwt.exceptions import PyJWTError
from starlette.datastructures import Headers, QueryParams
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import AuthConfig

logger = logging.getLogger(__name__)

#: WebSocket close code sent when a handshake is rejected: 1008 policy violation.
WEBSOCKET_POLICY_VIOLATION = 1008

#: Algorithms accepted from the identity proxy. Cloudflare Access signs RS256.
JWT_ALGORITHMS = ("RS256",)

#: Claim names that must be present in an accepted token.
REQUIRED_CLAIMS = ("exp", "iat", "iss", "aud")

#: Paths that require authentication whenever any mechanism is enabled. Paths
#: outside this set stay reachable so that a statically served UI shell (and the
#: login redirect that leads to it) can still load.
PROTECTED_PATHS = frozenset({"/api", "/ws", "/docs", "/redoc", "/openapi.json"})
PROTECTED_PREFIXES = ("/api/",)


def is_protected_path(path: str) -> bool:
    """Return True when ``path`` belongs to the authenticated API surface.

    The path is normalised first — percent-decoded, with duplicate slashes
    collapsed and ``.``/``..`` segments resolved — so that the gate can never be
    side-stepped by a path that the router downstream would resolve to a
    protected route. Matching is deliberately stricter than the router's.
    """
    normalized = "/" + "/".join(_normalized_segments(path))
    return normalized in PROTECTED_PATHS or normalized.startswith(PROTECTED_PREFIXES)


def _normalized_segments(path: str) -> list[str]:
    """Split ``path`` into resolved, non-empty segments."""
    segments: list[str] = []
    for segment in unquote(path).split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    return segments


@dataclass(frozen=True)
class JwtResult:
    """Outcome of verifying one identity token."""

    ok: bool
    reason: str = ""
    email: str | None = None


class JwtVerifier:
    """Verify a signed identity token against a remote key set.

    Signing keys are fetched from ``jwks_url`` and cached for ``jwks_ttl``
    seconds. Verification fails closed: if a key cannot be resolved, the token
    is rejected rather than trusted.
    """

    def __init__(
        self,
        *,
        jwks_url: str,
        issuer: str,
        audience: str,
        allowed_emails: frozenset[str] = frozenset(),
        jwks_ttl: int = 1800,
        algorithms: tuple[str, ...] = JWT_ALGORITHMS,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._allowed_emails = allowed_emails
        self._algorithms = list(algorithms)
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=jwks_ttl)

    def verify(self, token: str | None) -> JwtResult:
        """Return whether ``token`` is a valid, currently-valid identity token."""
        if not token:
            return JwtResult(ok=False, reason="no identity token presented")
        try:
            signing_key = self._client.get_signing_key_from_jwt(token).key
        except Exception as exc:  # network failure, unknown key id, malformed token
            logger.warning("Could not resolve a signing key for the presented token: %s", exc)
            return JwtResult(ok=False, reason="signing key unavailable")
        try:
            claims = jwt_decode(
                token,
                signing_key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except PyJWTError as exc:
            return JwtResult(ok=False, reason=f"invalid token: {exc}")

        email = claims.get("email")
        if self._allowed_emails and (email or "").lower() not in self._allowed_emails:
            return JwtResult(ok=False, reason="identity is not on the allowed list", email=email)
        return JwtResult(ok=True, email=email)


class AuthMiddleware:
    """Enforce the configured authentication mechanisms on protected paths.

    Handles both HTTP and WebSocket scopes. HTTP rejections return ``401`` with
    a ``WWW-Authenticate`` challenge when bearer auth is enabled; WebSocket
    handshakes are refused before the connection is accepted, which a server
    such as uvicorn surfaces to the client as an ``HTTP 403``.
    """

    def __init__(self, app: ASGIApp, config: AuthConfig) -> None:
        self.app = app
        self.config = config
        self.verifier = self._build_verifier(config)

    @staticmethod
    def _build_verifier(config: AuthConfig) -> JwtVerifier | None:
        if not config.jwt_enabled:
            return None
        if not (config.issuer or "").startswith("https://"):
            logger.warning(
                "CF_ACCESS_TEAM_DOMAIN is not an https origin (%s): signing keys will be "
                "fetched over an unauthenticated channel. Use https outside of local testing.",
                config.issuer,
            )
        return JwtVerifier(
            jwks_url=config.jwks_url,
            issuer=config.issuer,
            audience=config.jwt_audience,
            allowed_emails=config.jwt_allowed_emails,
            jwks_ttl=config.jwks_ttl,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self.config.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not is_protected_path(path):
            await self.app(scope, receive, send)
            return

        # Preflight requests never carry credentials, and CORS middleware may sit
        # outside this one. Answering them here would break browser access.
        if scope["type"] == "http" and scope.get("method", "").upper() == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        try:
            allowed, reason = self._authenticate(scope, headers)
        except Exception:
            # Defence in depth: no hostile input should be able to turn the auth
            # gate into a 500. Fail closed, and keep the traceback in the log.
            logger.exception("Authentication raised while handling %s %s", scope["type"], path)
            allowed, reason = False, "authentication error"
        if not allowed:
            logger.info("Rejected unauthenticated %s %s (%s)", scope["type"], path, reason)
            await self._reject(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _authenticate(self, scope: Scope, headers: Headers) -> tuple[bool, str]:
        """Return whether the request satisfies at least one enabled mechanism."""
        reasons: list[str] = []

        if self.config.bearer_enabled:
            presented = self._presented_token(scope, headers)
            expected = self.config.token or ""
            # Compare as bytes: compare_digest() raises TypeError on non-ASCII
            # str input, which an unauthenticated caller must not be able to
            # turn into a 500.
            if presented and secrets.compare_digest(presented.encode(), expected.encode()):
                return True, ""
            reasons.append("bearer token missing or invalid")

        if self.verifier is not None:
            result = self.verifier.verify(headers.get(self.config.jwt_header))
            if result.ok:
                return True, ""
            reasons.append(result.reason)

        return False, "; ".join(reasons) or "no authentication mechanism configured"

    def _presented_token(self, scope: Scope, headers: Headers) -> str:
        """Extract a bearer token from the request, or return an empty string."""
        authorization = headers.get("authorization", "")
        if authorization:
            scheme, _, credentials = authorization.partition(" ")
            if scheme.lower() == "bearer" and credentials.strip():
                return credentials.strip()

        # WebSocket clients in a browser cannot set request headers, so the token
        # may travel as a query parameter — but only on the WebSocket route, and
        # only when explicitly enabled, since query strings reach access logs.
        if scope["type"] == "websocket" and self.config.token_ws_query:
            token = QueryParams(scope.get("query_string", b"")).get("token", "")
            if token:
                return token
        return ""

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Refuse a request that satisfied no enabled mechanism."""
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": WEBSOCKET_POLICY_VIOLATION})
            return

        headers = {"WWW-Authenticate": "Bearer"} if self.config.bearer_enabled else {}
        response = JSONResponse(
            {"detail": "Not authenticated"}, status_code=401, headers=headers
        )
        await response(scope, receive, send)
