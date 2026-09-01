"""Regression tests for app.py's local-only request hardening -- see
CLAUDE.md's review notes on "the localhost server trusts any website that
can reach it." Runs the real Handler on an ephemeral port (see
conftest.live_server) rather than mocking the security logic in isolation,
so a future regression that moves code back out of the checked lock (or
otherwise bypasses do_GET/do_POST's _security_check() call) would actually
be caught here."""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from http.cookiejar import CookieJar


def _request(host, port, method, path, headers=None, body=None, cookiejar=None):
    # NOTE: `cookiejar or CookieJar()` would be wrong here -- an empty
    # CookieJar's __len__() is 0, which makes it falsy, so `or` would
    # silently replace the caller's real (but still-empty) jar with a
    # throwaway one on every call until it holds a cookie.
    jar = cookiejar if cookiejar is not None else CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=body,
        method=method,
        headers=headers or {},
    )
    try:
        return opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def test_response_headers_are_hardened(live_server):
    host, port = live_server
    jar = CookieJar()
    response = _request(host, port, "GET", "/", headers={"Host": f"{host}:{port}"}, cookiejar=jar)
    assert response.status == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert "frame-ancestors 'none'" in response.headers.get("Content-Security-Policy", "")
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert "ct_token=" in response.headers.get("Set-Cookie", "")
    assert "SameSite=Strict" in response.headers.get("Set-Cookie", "")


def test_server_header_does_not_leak_python_version(live_server):
    host, port = live_server
    response = _request(host, port, "GET", "/", headers={"Host": f"{host}:{port}"})
    server_header = response.headers.get("Server", "")
    assert "Python" not in server_header
    assert "BaseHTTP" not in server_header


def test_dns_rebinding_style_host_header_is_rejected_on_get(live_server):
    """Simulates the reported "Host: evil.example receives 200 OK" finding:
    a request whose Host header names a different domain than this server
    (as a DNS-rebound page's requests would still carry) must be rejected,
    even for a read-only GET."""
    host, port = live_server
    response = _request(host, port, "GET", "/status", headers={"Host": "evil.example"})
    assert response.status == 400


def test_dns_rebinding_style_host_header_is_rejected_on_post(live_server):
    host, port = live_server
    response = _request(host, port, "POST", "/stop", headers={"Host": "evil.example"}, body=b"")
    assert response.status == 400


def test_post_without_csrf_cookie_is_rejected(live_server):
    host, port = live_server
    response = _request(host, port, "POST", "/stop", headers={"Host": f"{host}:{port}"}, body=b"")
    assert response.status == 403


def test_post_with_valid_cookie_is_allowed(live_server):
    host, port = live_server
    jar = CookieJar()
    _request(host, port, "GET", "/", headers={"Host": f"{host}:{port}"}, cookiejar=jar)
    response = _request(host, port, "POST", "/stop", headers={"Host": f"{host}:{port}"}, body=b"", cookiejar=jar)
    assert response.status == 200


def test_post_with_valid_cookie_but_cross_origin_is_rejected(live_server):
    """A cross-site page cannot read/replay this server's cookie itself, but
    this exercises the independent Origin check as defense in depth -- it
    must reject on Origin mismatch alone, even if a cookie is somehow
    present."""
    host, port = live_server
    jar = CookieJar()
    _request(host, port, "GET", "/", headers={"Host": f"{host}:{port}"}, cookiejar=jar)
    response = _request(
        host,
        port,
        "POST",
        "/stop",
        headers={"Host": f"{host}:{port}", "Origin": "http://evil.example"},
        body=b"",
        cookiejar=jar,
    )
    assert response.status == 403


def test_post_with_matching_origin_and_cookie_is_allowed(live_server):
    host, port = live_server
    jar = CookieJar()
    _request(host, port, "GET", "/", headers={"Host": f"{host}:{port}"}, cookiejar=jar)
    response = _request(
        host,
        port,
        "POST",
        "/stop",
        headers={"Host": f"{host}:{port}", "Origin": f"http://{host}:{port}"},
        body=b"",
        cookiejar=jar,
    )
    assert response.status == 200


def test_get_does_not_require_csrf_cookie(live_server):
    """A plain top-level navigation is how the cookie gets set in the first
    place -- GET must not require it already, or the app could never load."""
    host, port = live_server
    response = _request(host, port, "GET", "/status", headers={"Host": f"{host}:{port}"})
    assert response.status == 200
