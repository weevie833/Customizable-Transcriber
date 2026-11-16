"""The update-available check (update_check.py, app.py /api/update-check).
GitHub is never contacted: fetch_latest_tag / the opener are replaced."""
import io
import json
import urllib.error
import urllib.request

import pytest

import update_check


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(update_check, "_cache", {"checked_at": None, "tag": None})
    monkeypatch.delenv("CT_NO_UPDATE_CHECK", raising=False)


def latest_is(monkeypatch, tag):
    calls = []
    monkeypatch.setattr(update_check, "fetch_latest_tag", lambda: calls.append(1) or tag)
    return calls


@pytest.mark.parametrize("text, expected", [
    ("0.5.4", (0, 5, 4)), ("v1.10.0", (1, 10, 0)), (" v2.0.1\n", (2, 0, 1)),
    ("dev", None), ("", None), ("1.2", None), ("v1.2.3-beta", None),
])
def test_parse_version(text, expected):
    assert update_check.parse_version(text) == expected


def test_newer_release_is_reported(monkeypatch):
    latest_is(monkeypatch, "v0.6.0")
    status = update_check.update_status("0.5.4")
    assert status["update_available"] is True
    assert status["latest"] == "0.6.0" and status["current"] == "0.5.4"
    assert status["release_url"].endswith("/releases/tag/v0.6.0")
    assert status["install_line"].endswith("install-mac.sh | bash")
    assert status["mac_download_url"].endswith("/releases/download/v0.6.0/Customizable-Transcriber-Mac.dmg")


def test_versions_compare_as_numbers_not_text(monkeypatch):
    latest_is(monkeypatch, "v0.10.0")
    assert update_check.update_status("0.9.9")["update_available"] is True


@pytest.mark.parametrize("current", ["0.5.4", "0.6.0"])
def test_same_or_older_release_is_not_an_update(monkeypatch, current):
    latest_is(monkeypatch, "v0.5.4")
    assert update_check.update_status(current) == {"current": current, "update_available": False}


@pytest.mark.parametrize("current", ["dev", ""])
def test_unknown_installed_version_never_checks(monkeypatch, current):
    calls = latest_is(monkeypatch, "v9.9.9")
    assert update_check.update_status(current)["update_available"] is False
    assert calls == []


def test_failed_check_shows_nothing(monkeypatch):
    latest_is(monkeypatch, None)
    assert update_check.update_status("0.5.4")["update_available"] is False


def test_can_be_turned_off(monkeypatch):
    calls = latest_is(monkeypatch, "v9.9.9")
    monkeypatch.setenv("CT_NO_UPDATE_CHECK", "1")
    assert update_check.update_status("0.5.4")["update_available"] is False
    assert calls == []


def test_answer_is_cached(monkeypatch):
    calls = latest_is(monkeypatch, "v0.6.0")
    update_check.latest_tag(now=1000)
    update_check.latest_tag(now=1000 + update_check.CHECK_INTERVAL_SECONDS - 1)
    assert len(calls) == 1
    update_check.latest_tag(now=1000 + update_check.CHECK_INTERVAL_SECONDS)
    assert len(calls) == 2


def test_failure_is_retried_sooner(monkeypatch):
    calls = latest_is(monkeypatch, None)
    update_check.latest_tag(now=0)
    update_check.latest_tag(now=update_check.RETRY_AFTER_SECONDS - 1)
    assert len(calls) == 1
    update_check.latest_tag(now=update_check.RETRY_AFTER_SECONDS)
    assert len(calls) == 2


class FakeOpener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return io.BytesIO(b"")


def redirect_to(location, code=302):
    headers = {"Location": location} if location is not None else {}
    return urllib.error.HTTPError(update_check.LATEST_URL, code, "Found", headers, None)


@pytest.mark.parametrize("outcome, expected", [
    (redirect_to("https://github.com/x/y/releases/tag/v0.6.0"), "v0.6.0"),
    (redirect_to("https://github.com/x/y/releases/tag/nightly"), None),
    (redirect_to("https://github.com/x/y/releases"), None),
    (redirect_to(None), None),
    (urllib.error.HTTPError(update_check.LATEST_URL, 404, "Not Found", {}, None), None),
    (urllib.error.URLError("offline"), None),
    (TimeoutError(), None),
    (None, None),    # a 200 with no redirect: no release published
])
def test_fetch_latest_tag_reads_the_redirect(monkeypatch, outcome, expected):
    opener = FakeOpener(outcome)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)
    assert update_check.fetch_latest_tag() == expected
    request, timeout = opener.requests[0]
    assert request.get_method() == "HEAD" and request.full_url == update_check.LATEST_URL
    assert timeout == update_check.TIMEOUT_SECONDS


def test_endpoint(live_server, monkeypatch):
    import app
    monkeypatch.setattr(app, "APP_VERSION", "0.5.4")
    latest_is(monkeypatch, "v0.6.0")
    host, port = live_server
    request = urllib.request.Request(f"http://{host}:{port}/api/update-check")
    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.load(response)
    assert body["update_available"] is True and body["latest"] == "0.6.0"
