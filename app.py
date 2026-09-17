from __future__ import annotations

import http.cookies
import json
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from customizable_transcription.core import (
    DEFAULT_MODEL,
    FILE_TYPE_EXTENSIONS,
    MODELS,
    count_source_files_by_type,
)
from batch_transcription import estimate_off_peak_savings
from profiles_store import (
    PROFILES_DIR,  # noqa: F401 -- re-exported for test monkeypatching, see comment below
    PROJECT_DIR,
    USER_DATA_DIR,
    # PROFILES_DIR/USER_PROFILES_DIR are never referenced directly below --
    # they're kept as re-exports solely so tests/conftest.py's
    # sandboxed_user_data fixture can monkeypatch.setattr(ctapp,
    # "PROFILES_DIR"/"USER_PROFILES_DIR", ...); every profile CRUD function
    # still reads profiles_store's own copy of the name (see
    # docs/DESIGN.md's "Codebase structure" section on this exact footgun).
    # Do not remove as a "dead import" cleanup without patching that fixture.
    USER_PROFILES_DIR,  # noqa: F401 -- re-exported for test monkeypatching, see comment above
    ensure_profiles_dir,
    load_profile,
    save_custom_profile,
)
from app_state import (
    APP_SETTINGS_FILE,
    USER_OUTPUTS_DIR,
    load_source_folder,
    lock,
    new_test_run_state,  # noqa: F401 -- re-exported; see tests/test_test_mode_key_scoping_and_failure_isolation.py
    state,
    surface_stale_off_peak_job,
    test_lock,
    test_state,
)
from http_utils import FormData, MAX_DOCX_XML_BYTES, extract_docx_text  # noqa: F401 -- re-exported for tests
from run_support import run_test_job  # noqa: F401 -- re-exported for tests
from pages import FOOTER_HTML
from pages.privacy import privacy_page
from pages.home import home_page
from pages.transcribe import page
from pages.test_mode import test_mode_page
from pages.prompt_builder import prompt_builder_page
from handlers.xls_conversion import XlsConversionHandlerMixin
from handlers.index_compare import IndexCompareHandlerMixin
from handlers.profiles import ProfilesHandlerMixin
from handlers.transcribe_run import TranscribeRunHandlerMixin
from handlers.transcribe_offpeak import TranscribeOffPeakHandlerMixin
from handlers.test_mode_run import TestModeRunHandlerMixin
from handlers.settings import SettingsHandlerMixin


HOST = "127.0.0.1"
PORT = 8765

# --- Local-only request hardening -------------------------------------------
# Binding to 127.0.0.1 does NOT stop a malicious web page open in the same
# browser from POSTing here: the browser's same-origin policy blocks that
# page's JS from *reading* the response, but never blocked it from *sending*
# the request. DNS rebinding (a domain that resolves to 127.0.0.1 only after
# the page has already loaded) can defeat even that read restriction. Three
# independent checks close this, each catching what the others miss:
#   1. Host header must literally name this server. A DNS-rebound request
#      still carries the attacker's own domain as Host, so this alone
#      defeats rebinding regardless of what the request's source IP is.
#   2. Origin header (sent by every modern browser on state-changing
#      requests) must match this server's own origin when present.
#   3. A random token, generated fresh each time the app starts and handed to
#      the browser as a SameSite=Strict cookie on first load, must come back
#      on every state-changing request. SameSite=Strict means the browser
#      will never attach it to a request initiated from a different site,
#      so a cross-site page has no way to produce it even if it guesses the
#      URL and endpoint shape exactly.
CSRF_COOKIE_NAME = "ct_token"
CSRF_TOKEN = secrets.token_urlsafe(32)
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}


def _host_is_allowed(host_header: str | None) -> bool:
    return bool(host_header) and host_header.strip().lower() in ALLOWED_HOSTS


def _origin_is_allowed(origin_header: str | None) -> bool:
    # No Origin header at all is normal for a plain top-level GET navigation
    # and for same-machine tools like curl -- only reject an Origin that is
    # actually present and wrong, never mere absence.
    if not origin_header:
        return True
    return origin_header.strip().lower() in ALLOWED_ORIGINS


def _cookie_token(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    jar: http.cookies.SimpleCookie = http.cookies.SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        # Deliberately broad (see docs/DESIGN.md's "Security hardening
        # history" section / exception-catch audit): the Cookie header is
        # attacker-controllable input reaching this security check on every
        # single request, before any other validation. SimpleCookie.load()
        # on a malformed value must never be allowed to crash request
        # handling -- that would turn a malformed cookie into a
        # denial-of-service against the CSRF check itself. Failing closed
        # (treat it as "no valid token", same as a missing cookie) is
        # correct regardless of what actually went wrong.
        return None
    morsel = jar.get(CSRF_COOKIE_NAME)
    return morsel.value if morsel else None


# PROJECT_DIR/PROFILES_DIR/USER_DATA_DIR/USER_PROFILES_DIR (imported above
# from profiles_store) are this app's own repo-root and profile directories.
# USER_OUTPUTS_DIR/APP_SETTINGS_FILE, the in-memory run state
# (state/test_state and their locks/events), and the source-folder settings
# functions all live in app_state.py (see its module docstring for why).
# Everything genuinely feature-specific -- XLS Conversion, Index Compare,
# profile CRUD, Transcribe/Test Mode run orchestration, the folder-picker/
# settings endpoints -- lives in handlers/*.py and (for shared run/profile/
# document logic) run_support.py; this module keeps only routing/dispatch
# and what's genuinely cross-cutting (the CSRF/Host/Origin checks, generic
# response helpers, static-asset serving). See docs/DESIGN.md's "Codebase
# structure" section.
STATIC_DIR = PROJECT_DIR / "static"


def migrate_legacy_outputs_and_settings() -> None:
    """Outputs and app_settings.json used to live inside PROJECT_DIR itself
    (see USER_OUTPUTS_DIR/APP_SETTINGS_FILE above) -- the same
    folder-replace-safety problem profiles_store.ensure_profiles_dir()'s own
    legacy-rename migration solves for profiles, just for app.py's own data
    instead (which is why this is a separate function here rather than
    folded into that one -- profiles_store.py doesn't know about
    USER_OUTPUTS_DIR/APP_SETTINGS_FILE and shouldn't need to). Move any
    pre-existing content out, best-effort, so this fix doesn't silently
    orphan a user's already-generated transcriptions or their remembered
    source folder the first time they update into this version."""
    legacy_outputs_dir = PROJECT_DIR / "outputs"
    if legacy_outputs_dir.is_dir():
        if not USER_OUTPUTS_DIR.exists():
            try:
                USER_OUTPUTS_DIR.parent.mkdir(parents=True, exist_ok=True)
                legacy_outputs_dir.rename(USER_OUTPUTS_DIR)
            except OSError:
                pass
        else:
            # Both exist -- this used to skip the migration outright here,
            # silently orphaning every legacy output (the common case: the
            # app has already been run at least once since updating, which
            # is exactly when USER_OUTPUTS_DIR gets auto-created below, so
            # "both exist" isn't a rare edge case, it's what a normal
            # gradual update looks like). Merge file-by-file instead.
            # Never overwrites: a real name collision leaves the legacy copy
            # in place rather than risking the newer file. Best-effort per
            # file, same as the whole-directory rename above.
            for item in legacy_outputs_dir.iterdir():
                target = USER_OUTPUTS_DIR / item.name
                if target.exists():
                    continue
                try:
                    item.rename(target)
                except OSError:
                    pass
            try:
                legacy_outputs_dir.rmdir()
            except OSError:
                pass  # not empty (a collision left something behind) or otherwise in use -- harmless to leave
    USER_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    legacy_settings_file = PROJECT_DIR / "app_settings.json"
    if legacy_settings_file.is_file() and not APP_SETTINGS_FILE.exists():
        try:
            USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
            legacy_settings_file.rename(APP_SETTINGS_FILE)
        except OSError:
            pass


def getting_started_page() -> str:
    """Full orientation content, in collapsible sections -- one <details> per
    starred heading in the source doc the user supplied (Getting Started.rtf),
    bilingual via the same data-lang-block pattern privacy_page()/home_page()
    already use (static/i18n.js toggles [data-lang-block] visibility by the
    lang cookie), since this is long narrative prose rather than short UI
    strings i18n.js's dictionary-lookup approach is built for.

    The section content itself lives in GETTING_STARTED.html/.it.html (plain
    HTML fragments, not markdown -- unlike privacy_page()'s PRIVACY.md, there's
    no markdown-to-HTML render step here) so it can be edited on its own
    without touching this function's page shell (nav/footer -- the CSS lives
    in static/getting-started.css). Read in and substituted via plain string
    replace, not an f-string, since GETTING_STARTED.html/.it.html's own
    content could contain literal `{`/`}` characters that would otherwise
    need escaping."""
    content_en = (PROJECT_DIR / "GETTING_STARTED.html").read_text(encoding="utf-8")
    content_it = (PROJECT_DIR / "GETTING_STARTED.it.html").read_text(encoding="utf-8")
    page = """<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Getting Started</title>
  <script src="/static/i18n.js" defer></script>
  <link rel="stylesheet" href="/static/base.css">
  <link rel="stylesheet" href="/static/getting-started.css">
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<main id="main-content" tabindex="-1">
  <header class="site-header">
    <h1 class="sr-only">Getting Started</h1>
    <div class="header-nav-row">
      <nav class="site-nav" aria-label="Primary navigation">
        <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
        <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
        <a class="nav-link" href="/transcribe">Transcribe</a>
        <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
        <a class="nav-link" href="/test-mode">Test Mode</a>
      </nav>
      <div class="header-right">
        <a class="nav-link nav-secondary" href="/getting-started" aria-current="page">Getting Started</a>
        <div class="lang-toggle" role="group" aria-label="Language / Lingua">
          <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
          <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
        </div>
      </div>
    </div>
  </header>

  <div data-lang-block="en">
%%GETTING_STARTED_EN%%  </div>

  <div data-lang-block="it" hidden>
%%GETTING_STARTED_IT%%  </div>

  %%FOOTER%%
</main>
</body>
</html>"""
    return (
        page.replace("%%GETTING_STARTED_EN%%", content_en)
        .replace("%%GETTING_STARTED_IT%%", content_it)
        .replace("%%FOOTER%%", FOOTER_HTML)
    )


# Single source of truth for the version shown in every page's footer (see
# /version below and static/i18n.js's fetch of it). A plain VERSION file, not
# a git-derived value (commit hash/tag), because real end users run a
# downloaded-and-unzipped copy with no .git directory at all -- see README's
# "download a fresh copy, replace the old folder" update path. Bumped by hand
# per semver (MAJOR.MINOR.PATCH) as part of each commit to main.
try:
    APP_VERSION = (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    APP_VERSION = "dev"


class Handler(
    XlsConversionHandlerMixin,
    IndexCompareHandlerMixin,
    ProfilesHandlerMixin,
    TranscribeRunHandlerMixin,
    TranscribeOffPeakHandlerMixin,
    TestModeRunHandlerMixin,
    SettingsHandlerMixin,
    BaseHTTPRequestHandler,
):
    # Nearly every method on the mixins above wraps its entire body in a
    # single `try: ... except Exception as exc: self.respond_json({"error":
    # ...})` (or the redirect-based equivalent for form-POST handlers). This
    # is audited and deliberate, not an unreviewed catch-all (see
    # docs/DESIGN.md's "Security hardening history" section): each of these
    # methods is one HTTP request's entire processing, and this app has no
    # other layer between a handler method and the raw socket -- an
    # exception type nobody anticipated must still turn into a clean,
    # readable error response, not an unhandled crash of this request's
    # thread or a raw client-visible 500. Narrowing any of these to specific
    # exception types would make a genuinely unexpected failure (a library
    # edge case, a bug) surface as a broken connection instead of the same
    # clear error message every anticipated failure already gets -- worse
    # for both users and debugging, not better. A handler-specific comment
    # is added only where the reason is not this general one (e.g.
    # _cookie_token()'s fail-safe parsing of untrusted input, above).
    def version_string(self) -> str:
        # Suppresses the default "BaseHTTP/x.x Python/3.x.x" Server header,
        # which otherwise hands a would-be attacker the exact Python version
        # for free.
        return "CustomizableTranscription"

    def end_headers(self) -> None:
        # Applied to every single response (JSON, HTML, downloads, redirects,
        # error pages) since they all funnel through this one call.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            # 'unsafe-inline' removed from both script-src and style-src --
            # see docs/DESIGN.md's "Security hardening history" section.
            # Every page's <script>/<style> content now loads from
            # /static/*.js and *.css (or, for genuinely per-request dynamic
            # data, a <script type="application/json"> data island -- inert
            # to the browser's JS engine, so script-src never governs it;
            # see json_data_island_html() in pages/__init__.py). This is a
            # real second layer of defense now: a future HTML/script-
            # injection bug (this app has had exactly one, in a profile
            # label once embedded via bare json.dumps()) can no longer
            # execute as script just because it lands inside a
            # <script>/<style> tag.
            "default-src 'self'; script-src 'self'; "
            "style-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
        )
        # "same-origin", not "no-referrer": per the Fetch spec, a top-level
        # form-POST navigation's Origin header is derived from the referring
        # page's own Referrer-Policy -- "no-referrer" forces Origin to the
        # literal string "null" on exactly this kind of request (confirmed
        # live in Chrome), which then fails _security_check()'s Origin
        # allowlist below and makes every real Save button 403 with
        # "cross-origin request rejected", even though the request is
        # genuinely same-origin. "same-origin" gives the same practical
        # privacy guarantee (Referer never leaks to a different origin --
        # this app never links out) without nulling Origin on same-origin
        # requests, which is all this app ever makes.
        self.send_header("Referrer-Policy", "same-origin")
        # Re-sent on every response, not just the first -- idempotent (the
        # browser just keeps the same value) and means the check below never
        # has to special-case "this is the first load."
        self.send_header(
            "Set-Cookie",
            f"{CSRF_COOKIE_NAME}={CSRF_TOKEN}; Path=/; SameSite=Strict; HttpOnly",
        )
        super().end_headers()

    def _send_security_error(self, status: int, message: str) -> None:
        data = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _security_check(self, state_changing: bool) -> bool:
        """Host validation runs for every request (closes DNS rebinding on
        both reads and writes); Origin + CSRF-cookie validation runs only for
        state-changing requests, where a cross-site page could otherwise
        trigger a real side effect (stop a job, delete a profile, open the
        native folder picker) with no way to read the response back."""
        if not _host_is_allowed(self.headers.get("Host")):
            self._send_security_error(400, "Bad Request: unrecognized Host header.")
            return False
        if state_changing:
            if not _origin_is_allowed(self.headers.get("Origin")):
                self._send_security_error(403, "Forbidden: cross-origin request rejected.")
                return False
            if _cookie_token(self.headers.get("Cookie")) != CSRF_TOKEN:
                self._send_security_error(
                    403,
                    "Forbidden: missing or invalid request token. Reload the page and try again.",
                )
                return False
        return True

    def do_GET(self) -> None:
        if not self._security_check(state_changing=False):
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/xls-conversion", "/xls-conversion/"}:
            self.serve_xls_asset("index.html")
            return

        if parsed.path.startswith("/xls-conversion/"):
            self.serve_xls_asset(parsed.path.removeprefix("/xls-conversion/"))
            return

        if parsed.path.startswith("/static/"):
            self.serve_static_asset(parsed.path.removeprefix("/static/"))
            return

        if parsed.path == "/status":
            self.status()
            return

        if parsed.path == "/version":
            self.respond_json({"version": APP_VERSION})
            return

        if parsed.path == "/api/models":
            # Single source of truth for the model list: Transcribe, Test
            # Mode, and Prompt Builder build their <select> options directly
            # from the MODELS dict server-side (they're rendered as Python
            # f-strings), but xls_conversion/index.html is a static asset
            # with no templating -- this lets its app.js populate the same
            # list at load time instead of keeping its own hand-maintained
            # copy that silently drifts out of sync with MODELS.
            self.respond_json(
                {
                    "models": [{"id": model_id, "label": label} for model_id, label in MODELS.items()],
                    "default": DEFAULT_MODEL,
                }
            )
            return

        if parsed.path == "/api/offpeak-cost-estimate":
            # Read-only. Takes no client-supplied PATH at all -- counts
            # whatever source folder is already stored server-side (picked
            # via /api/pick-source-folder or typed into /api/set-source-folder),
            # never a path the request itself names. `model` and `file_type`
            # are small, validated enum values, not paths -- reused directly
            # against MODELS/FILE_TYPE_EXTENSIONS the same way selected_model()/
            # selected_file_type() already validate them for a real run.
            # `profile_id` is resolved through load_profile() (server-side,
            # same as run_off_peak() itself) purely to read pageLayout --
            # never returned to the client, matching profiles_for_browser()'s
            # own rule that pb_answers never reaches the browser.
            query = urllib.parse.parse_qs(parsed.query)
            model = (query.get("model") or [DEFAULT_MODEL])[0]
            file_type = (query.get("file_type") or ["jpeg"])[0]
            profile_id = (query.get("profile_id") or [""])[0]
            if model not in MODELS or file_type not in FILE_TYPE_EXTENSIONS:
                self.respond_json({"error": "Invalid model or file type."}, status=400)
                return
            folder = load_source_folder()
            try:
                # A stored source folder can point at a path that no longer
                # exists (moved, renamed, on unmounted external media, or a
                # settings file left over from a different machine) --
                # count_source_files_by_type() raises FileNotFoundError in
                # that case. This is a purely informational estimate, not a
                # precondition for anything, so it degrades to "0 images
                # found" rather than surfacing an error the user has to act
                # on -- the real run's own preflight_source_file_type()
                # still raises its own clear error at submission time either
                # way, this just must not crash a background estimate fetch.
                counts = count_source_files_by_type(folder) if folder is not None else {}
            except OSError:
                counts = {}
            image_count = counts.get(file_type, 0)
            page_layout = ""
            if profile_id:
                try:
                    profile = load_profile(profile_id)
                    pb_answers = profile.get("pb_answers") or {}
                    page_layout = str((pb_answers.get("fields") or {}).get("pageLayout", ""))
                except Exception:
                    page_layout = ""
            self.respond_json(
                {
                    "image_count": image_count,
                    "estimate_text": estimate_off_peak_savings(image_count, page_layout, model),
                }
            )
            return

        if parsed.path == "/download":
            self.download()
            return

        if parsed.path in {"/test-mode", "/test-mode/"}:
            self.respond(test_mode_page())
            return

        if parsed.path in {"/prompt-builder", "/prompt-builder/"}:
            self.respond(prompt_builder_page())
            return

        if parsed.path in {"/privacy", "/privacy/"}:
            self.respond(privacy_page())
            return

        if parsed.path in {"/transcribe", "/transcribe/"}:
            self.respond(page())
            return

        if parsed.path in {"/getting-started", "/getting-started/"}:
            self.respond(getting_started_page())
            return

        if parsed.path == "/prompt-builder/export-profile":
            self.export_prompt_builder_profile(dict(urllib.parse.parse_qsl(parsed.query)))
            return

        if parsed.path == "/test-mode/status":
            self.test_status()
            return

        if parsed.path.startswith("/test-mode/download/"):
            self.test_download(parsed.path.removeprefix("/test-mode/download/"))
            return

        if parsed.path != "/":
            self.redirect_home()
            return

        self.respond(home_page())

    def do_POST(self) -> None:
        if not self._security_check(state_changing=True):
            return
        if urllib.parse.urlparse(self.path).path == "/api/xls-conversion/upload":
            self.upload_xls_source()
            return

        if urllib.parse.urlparse(self.path).path == "/api/xls-conversion/parse":
            self.parse_xls_source()
            return

        if urllib.parse.urlparse(self.path).path == "/api/xls-conversion/preflight":
            self.preflight_xls_source()
            return

        if urllib.parse.urlparse(self.path).path == "/api/xls-conversion/detect-languages":
            self.detect_xls_languages()
            return

        if urllib.parse.urlparse(self.path).path == "/api/xls-conversion/combine":
            self.combine_xls_languages()
            return

        if urllib.parse.urlparse(self.path).path == "/api/test-mode/compare":
            self.compare_test()
            return

        if urllib.parse.urlparse(self.path).path == "/api/test-mode/compare-report":
            self.compare_report()
            return

        if urllib.parse.urlparse(self.path).path == "/api/index-compare/suggest-mapping":
            self.suggest_index_mapping()
            return

        if urllib.parse.urlparse(self.path).path == "/api/index-compare/analyze":
            self.analyze_index_compare()
            return

        if urllib.parse.urlparse(self.path).path == "/api/index-compare/report":
            self.index_compare_report()
            return

        if urllib.parse.urlparse(self.path).path == "/api/pick-source-folder":
            self.pick_source_folder()
            return

        if urllib.parse.urlparse(self.path).path == "/api/set-source-folder":
            self.set_source_folder()
            return

        if urllib.parse.urlparse(self.path).path == "/api/open-outputs-folder":
            self.open_outputs_folder()
            return

        if self.path == "/stop":
            self.stop_job()
            return

        if self.path == "/reset":
            self.reset()
            return

        if self.path == "/save-profile":
            self.save_profile()
            return

        if self.path == "/prompt-builder/save-profile":
            self.save_prompt_builder_profile()
            return

        if self.path == "/prompt-builder/preflight-test":
            self.preflight_test_prompt_builder()
            return

        if self.path == "/prompt-builder/save-draft":
            self.save_prompt_builder_draft()
            return

        if self.path == "/prompt-builder/import-profile":
            self.import_prompt_builder_profile()
            return

        if self.path == "/delete-profile":
            self.delete_profile()
            return

        if self.path == "/test-mode/run":
            self.run_test()
            return

        if self.path == "/test-mode/stop":
            self.stop_test_job()
            return

        if self.path == "/test-mode/reset":
            self.reset_test()
            return

        if self.path == "/test-mode/delete-profile":
            self.delete_test_profile()
            return

        if self.path == "/test-mode/queue/add":
            self.add_to_queue()
            return

        if self.path == "/test-mode/queue/remove":
            self.remove_from_queue()
            return

        if self.path == "/run-offpeak":
            self.run_off_peak()
            return

        if self.path != "/run":
            self.send_error(404)
            return

        self.run_transcription()

    def serve_static_asset(self, relative_path: str) -> None:
        relative = Path(relative_path or "")
        if not relative_path or relative.is_absolute() or ".." in relative.parts:
            self.send_error(404)
            return

        path = (STATIC_DIR / relative).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(404)
            return

        if not path.is_file():
            self.send_error(404)
            return

        content_types = {
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }
        # Downloadable binaries (Prompt Builder's offline worksheet DOCX/ZIP
        # files) are also served through this route -- a whitelisted second
        # set of extensions, sent as attachments, rather than opening the
        # content_types whitelist above to arbitrary types.
        download_types = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".zip": "application/zip",
        }
        suffix = path.suffix.lower()
        content_type = content_types.get(suffix) or download_types.get(suffix)
        if not content_type:
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if suffix in download_types:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def respond(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        # Every dynamic page rendered through this method embeds current run
        # state and saved profile content (role/reference/output-format text,
        # lexicons, local file paths) -- no-store keeps a shared machine's
        # browser cache/history from retaining it, matching the no-store
        # policy already applied to every JSON/status/download response.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def respond_json(self, payload: dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def redirect_home(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def redirect_transcribe(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/transcribe")
        self.end_headers()

    def redirect_test_mode(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/test-mode")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    ensure_profiles_dir()
    migrate_legacy_outputs_and_settings()
    with lock:
        state["profile_id"] = ""
    surface_stale_off_peak_job()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Customizable Transcription Interface running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
