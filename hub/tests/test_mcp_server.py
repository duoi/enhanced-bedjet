"""Tests for the stdio MCP proxy's Hub client.

The MCP server is a standalone, dependency-free script rather than part of the
``bedjet_hub`` package, so it is loaded by path.
"""

import importlib.util
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

MCP_SERVER_PATH = Path(__file__).resolve().parents[2] / "mcp" / "server.py"


@pytest.fixture(scope="module")
def mcp():
    """Load mcp/server.py without executing its stdio loop."""
    spec = importlib.util.spec_from_file_location("bedjet_mcp_server", MCP_SERVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    """Minimal stand-in for the object urlopen() returns."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture
def sent_requests(monkeypatch):
    """Capture outbound requests, returning canned JSON for each."""
    captured = []

    def fake_urlopen(request, timeout=None):
        captured.append(request)
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


@pytest.fixture(autouse=True)
def clean_token(monkeypatch):
    monkeypatch.delenv("HUB_API_TOKEN", raising=False)


def test_hub_url_defaults_to_localhost(mcp):
    assert mcp.HUB_URL == "http://localhost:8265"


def test_headers_are_empty_without_a_token(mcp):
    assert mcp.hub_headers() == {}


def test_headers_include_the_bearer_token(mcp, monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    assert mcp.hub_headers() == {"Authorization": "Bearer s3cret"}


def test_headers_preserve_caller_supplied_entries(mcp, monkeypatch):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    headers = mcp.hub_headers({"Content-Type": "application/json"})
    assert headers == {
        "Content-Type": "application/json",
        "Authorization": "Bearer s3cret",
    }


def test_get_sends_the_authorization_header(mcp, monkeypatch, sent_requests):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    assert mcp.hub_get("/device") == {"ok": True}
    assert sent_requests[0].get_header("Authorization") == "Bearer s3cret"
    assert sent_requests[0].full_url == "http://localhost:8265/api/device"


def test_post_sends_content_type_and_authorization(mcp, monkeypatch, sent_requests):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    assert mcp.hub_post("/device/mode", {"mode": "heat"}) == {"ok": True}
    request = sent_requests[0]
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Authorization") == "Bearer s3cret"


def test_put_sends_content_type_and_authorization(mcp, monkeypatch, sent_requests):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    mcp.hub_put("/preferences", {"temperatureUnit": "celsius"})
    request = sent_requests[0]
    assert request.get_method() == "PUT"
    assert request.get_header("Authorization") == "Bearer s3cret"


def test_delete_uses_the_delete_verb(mcp, monkeypatch, sent_requests):
    monkeypatch.setenv("HUB_API_TOKEN", "s3cret")
    mcp.hub_delete("/programs/abc")
    request = sent_requests[0]
    assert request.get_method() == "DELETE"
    assert request.get_header("Authorization") == "Bearer s3cret"


def test_requests_omit_the_header_when_no_token_is_configured(mcp, sent_requests):
    mcp.hub_get("/device")
    assert sent_requests[0].get_header("Authorization") is None


@pytest.mark.parametrize(
    "call",
    [
        lambda mcp: mcp.hub_get("/device"),
        lambda mcp: mcp.hub_post("/device/mode", {"mode": "heat"}),
        lambda mcp: mcp.hub_put("/preferences", {"temperatureUnit": "celsius"}),
        lambda mcp: mcp.hub_delete("/programs/abc"),
    ],
    ids=["get", "post", "put", "delete"],
)
def test_unauthorized_responses_raise_an_actionable_error(mcp, monkeypatch, call):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(mcp.RpcError) as excinfo:
        call(mcp)
    assert "HUB_API_TOKEN" in excinfo.value.message


def test_unreachable_hub_reports_a_distinct_error(mcp, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(mcp.RpcError) as excinfo:
        mcp.hub_get("/device")
    assert "unreachable" in excinfo.value.message.lower()


def test_non_401_http_errors_are_reported(mcp, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 500, "Server Error", {}, io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(mcp.RpcError) as excinfo:
        mcp.hub_get("/device")
    assert "500" in excinfo.value.message
