"""reviews/CODEX_REVIEW_8.md L-1: the app answers an identity check the
launchers can tell apart from any other local service."""

from __future__ import annotations

import json
import urllib.request

import app as ctapp


def test_health_endpoint_identifies_the_app(live_server):
    host, port = live_server
    request = urllib.request.Request(f"http://{host}:{port}/api/health", headers={"Host": f"{host}:{port}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        data = json.loads(response.read())
    assert data["app"] == ctapp.HEALTH_APP_ID
