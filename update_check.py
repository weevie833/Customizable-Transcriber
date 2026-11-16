"""Tells the app whether a newer release exists on GitHub.

One request to github.com/<repo>/releases/latest, which redirects to the
latest release's tag page; the tag is read from the final URL, so there is no
JSON API (and no API rate limit) involved. Nothing about the user or their
data is sent. The answer is cached in memory: a successful check is reused
for CHECK_INTERVAL_SECONDS, a failed one for RETRY_AFTER_SECONDS, so opening
pages never repeats the request. Any failure just means "no update shown".

CT_NO_UPDATE_CHECK=1 turns the check off (documented in PRIVACY.md)."""

from __future__ import annotations

import os
import re
import sys
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = "weevie833/Customizable-Transcriber"
LATEST_URL = f"https://github.com/{REPO}/releases/latest"
# Attached to each release by .github/workflows/mac-release.yml.
MAC_DMG_NAME = "Customizable-Transcriber-Mac.dmg"
INSTALL_LINE = (
    f"curl -fsSL https://raw.githubusercontent.com/{REPO}/main/install-mac.sh | bash"
)
TIMEOUT_SECONDS = 5
CHECK_INTERVAL_SECONDS = 12 * 60 * 60
RETRY_AFTER_SECONDS = 60 * 60

_lock = threading.Lock()
_cache: dict[str, object] = {"checked_at": None, "tag": None}

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match((text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None    # read the Location header instead of downloading the tag page


def _ssl_context() -> ssl.SSLContext:
    # The installers' standalone Python may not find the system's certificates;
    # certifi (already a dependency) always works.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_latest_tag() -> str | None:
    """The latest release's tag (e.g. "v0.5.4"), or None on any failure."""
    opener = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPSHandler(context=_ssl_context()))
    request = urllib.request.Request(LATEST_URL, method="HEAD",
                                     headers={"User-Agent": "Customizable-Transcriber"})
    location = ""
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS):
            return None    # no redirect: no release published
    except urllib.error.HTTPError as err:
        if err.code in (301, 302, 303, 307, 308):
            location = err.headers.get("Location", "")
    except Exception:
        return None
    match = re.search(r"/releases/tag/([^/?#]+)$", location)
    tag = urllib.parse.unquote(match.group(1)) if match else None
    return tag if tag and parse_version(tag) else None


def latest_tag(now: float | None = None) -> str | None:
    now = time.time() if now is None else now
    with _lock:
        checked_at = _cache["checked_at"]
        if checked_at is not None:
            wait = CHECK_INTERVAL_SECONDS if _cache["tag"] else RETRY_AFTER_SECONDS
            if now - float(checked_at) < wait:
                return _cache["tag"]  # type: ignore[return-value]
        # Held across the request on purpose: pages loading at once share one check.
        tag = fetch_latest_tag()
        _cache["checked_at"] = now
        _cache["tag"] = tag
        return tag


def platform_kind() -> str:
    """Which update instructions to show."""
    if sys.platform == "darwin":
        return "mac"
    if sys.platform == "win32":
        return "windows"
    return "other"


def update_status(current_version: str) -> dict[str, object]:
    """What /api/update-check returns. update_available is True only when both
    versions parse and the release is strictly newer."""
    result: dict[str, object] = {"current": current_version, "update_available": False}
    if os.environ.get("CT_NO_UPDATE_CHECK"):
        return result
    current = parse_version(current_version)
    if current is None:    # "dev" or an unreadable VERSION file
        return result
    tag = latest_tag()
    latest = parse_version(tag or "")
    if latest is None or latest <= current:
        return result
    result.update({
        "update_available": True,
        "latest": ".".join(str(part) for part in latest),
        "release_url": f"https://github.com/{REPO}/releases/tag/{tag}",
        "platform": platform_kind(),
        "install_line": INSTALL_LINE,
        "mac_download_url": f"https://github.com/{REPO}/releases/download/{tag}/{MAC_DMG_NAME}",
    })
    return result
