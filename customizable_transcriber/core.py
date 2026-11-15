from __future__ import annotations

import base64
import os
import random
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic
import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from customizable_transcriber import page_zoom, usage_ledger
from customizable_transcriber.year_check import apply_year_check

FILE_TYPE_EXTENSIONS = {
    "jpeg": frozenset({".jpg", ".jpeg"}),
    "png": frozenset({".png"}),
}
SUPPORTED_SOURCE_EXTENSIONS = frozenset(
    extension
    for extensions in FILE_TYPE_EXTENSIONS.values()
    for extension in extensions
)
FILE_TYPE_MIME = {
    "jpeg": "image/jpeg",
    "png": "image/png",
}
# Leading-byte signatures for detecting a file's real format from its own
# content, independent of whatever extension the browser/OS attached to it.
# Used by Prompt Builder's Preflight Test, which takes a single ad-hoc upload
# rather than a pre-vetted source folder -- see sniff_file_type().
_MAGIC_BYTES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
)


def sniff_file_type(data: bytes) -> str | None:
    """Detect jpeg/png from the file's own leading bytes (a FILE_TYPE_EXTENSIONS
    key), or None if it matches none of them. Trusting content over a filename
    extension means a mislabeled or renamed upload is still read correctly --
    or cleanly rejected as unsupported -- rather than silently sent to the AI
    provider tagged with the wrong MIME type."""
    for signature, file_type in _MAGIC_BYTES:
        if data.startswith(signature):
            return file_type
    return None
# Single source of truth for every model id/label the app offers, in every
# dropdown (Transcribe, Test Mode, Prompt Builder, XLS Conversion) and every
# DOCX/report label that names a model. Lives here (not app.py, where it
# used to be defined) so test_mode/report_docx.py can use it too without
# creating an app.py <-> test_mode circular import -- app.py already imports
# from this module for DEFAULT_MODEL/provider_for_model() etc., and
# test_mode/report_docx.py only needs this one dict, not anything else from
# app.py.
MODELS = {
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview - higher accuracy",
    "gemini-2.5-pro": "Gemini 2.5 Pro - stable, high-accuracy baseline",
    "claude-opus-5-5": "Claude Opus 5.5 - highest accuracy, stronger visual reading",
    "claude-opus-5": "Claude Opus 5 - high accuracy",
    "claude-sonnet-5": "Claude Sonnet 5 - balanced speed / intelligence",
}

# Reverted from gemini-2.5-pro back to the preview model, 2026-09, on the
# user's own explicit instruction after their Test Mode comparisons showed
# gemini-3.1-pro-preview producing meaningfully better transcriptions.
# Accepted knowingly, not overlooked: this is Google's only Gemini 3.1 Pro
# release -- there is no separate, non-preview "Gemini 3.1 Pro" to fall back
# to (confirmed against Google's own model docs, which list only
# gemini-3.1-pro-preview and a -customtools variant under Gemini 3.1 Pro) --
# so the preview-deprecation risk the gemini-2.5-pro default was chosen to
# avoid is real and still applies. If Google deprecates this model, every
# profile/run relying on this default breaks until DEFAULT_MODEL is updated
# again; gemini-2.5-pro remains in MODELS above as the fallback to switch
# back to. Users who want the stable baseline instead can still select
# "Gemini 2.5 Pro" from the model dropdown.
DEFAULT_MODEL = "gemini-3.1-pro-preview"
# A per-call bound for the real Transcribe/Test Mode batch, not the tight
# PREFLIGHT_TIMEOUT_SECONDS-style bound app.py uses for a single foreground
# call. Genuinely slow-but-working images are common and shouldn't be
# aborted, but with no bound at all a fully hung connection can never be
# interrupted -- Stop only takes effect between images, so one dead request
# would otherwise wait forever rather than surfacing as a single failed
# image and letting the batch continue. 10 minutes is long enough that a
# real response essentially always arrives well before it.
BATCH_REQUEST_TIMEOUT_SECONDS = 600

# The "Checking API key..." call that opens every run is one tiny request, so a
# minute is generous -- and it can't be interrupted by Stop while it blocks, so the
# bound (not the SDK's own, much longer default) is what keeps a network stall from
# leaving the UI stuck (reviews/CODEX_REVIEW.md M-3).
KEY_CHECK_TIMEOUT_SECONDS = 60
# Per-file ceiling for a batch source image -- see reviews/CODEX_REVIEW.md finding
# M-1 / reviews/HUMAN_DECISIONS.md. Matches app.py's own MAX_DOCX_BYTES (50MB),
# chosen as a size no legitimate archival page scan should realistically
# exceed while still bounding the memory a single mislabeled/pathological
# file can consume before it's even sent to a provider.
MAX_BATCH_IMAGE_BYTES = 50_000_000
USER_INSTRUCTION = "Transcribe and translate this document word-for-word."
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
DATE_FOLDER_PATTERN = re.compile(r"^(\d{4})\s+([A-Za-z]+)\s+(\d{1,2})$")


@dataclass(frozen=True)
class TranscriptionConfig:
    image_folder: Path
    output_file: Path
    prompt_file: Path
    model: str = DEFAULT_MODEL
    delay_seconds: float = 2.0
    reverse_order: bool = False
    include_thoughts: bool = False
    system_prompt: str | None = None
    api_key_override: str | None = None
    source_extensions: frozenset[str] = field(default_factory=lambda: SUPPORTED_SOURCE_EXTENSIONS)
    # Page zoom (page_zoom.py): Gemini only; ignored for Claude.
    zoom_pages: bool = False
    # Labels for the usage ledger only; nothing else reads them.
    profile_id: str = ""
    profile_label: str = ""


@dataclass(frozen=True)
class ImageResult:
    filename: str
    ok: bool
    text: str


# The only two variables this app's .env support was ever designed for --
# see .env.example, which documents exactly these two and nothing else.
_ENV_FILE_ALLOWED_KEYS = frozenset({"GEMINI_API_KEY", "ANTHROPIC_API_KEY"})


def load_env_file(path: Path) -> None:
    """Loads GEMINI_API_KEY/ANTHROPIC_API_KEY from a .env file into the
    process environment, if not already set. Deliberately narrower than a
    generic dotenv loader in two ways: (1) only the two keys this app
    actually documents/uses are copied -- an unrelated line (a stray PROXY
    or PATH override, say) in a hand-edited .env can't change this
    process's network routing or executable resolution as a side effect of
    just wanting to store an API key; (2) an already-set environment
    variable is never overwritten, matching the common expectation (and
    python-dotenv's own default) that an explicitly exported value takes
    precedence over a dotenv file, not the other way around."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _ENV_FILE_ALLOWED_KEYS or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("\"'")


def api_key(project_dir: Path) -> str:
    load_env_file(project_dir / ".env")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env or export it before running."
        )
    if key == "your_api_key_here":
        raise RuntimeError("GEMINI_API_KEY is still set to the placeholder value.")
    return key


def claude_api_key(project_dir: Path) -> str:
    load_env_file(project_dir / ".env")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or export it before running."
        )
    if key == "your_api_key_here":
        raise RuntimeError("ANTHROPIC_API_KEY is still set to the placeholder value.")
    return key


def provider_for_model(model: str) -> str:
    return "claude" if model.startswith("claude-") else "gemini"


def key_looks_like_claude(api_key: str) -> bool:
    """Loose, prefix-based sanity check -- not a substitute for a real API
    call. Anthropic keys reliably start with "sk-ant-", so this is enough to
    catch a key pasted into the wrong provider's field; Gemini/Google AI
    keys don't have one universal prefix, so there's no equivalent positive
    check for those, only "this doesn't look like a Claude key."

    Test Mode's API key fields are scoped by provider (one Gemini field, one
    Claude field -- see required_providers()/run_test() in app.py), so the
    validation this enables is a direct per-field check: does the Claude
    field's value look like a Claude key, and does the Gemini field's value
    *not* look like one (which would mean a Claude key got pasted into the
    wrong field). There's no longer a model-driven key_matches_provider()
    wrapper, since which provider a given key is *for* is now declared by
    which field it was typed into, not inferred from a model selection."""
    return api_key.strip().startswith("sk-ant-")


def parse_date_folder(name: str) -> tuple[int, int, int] | None:
    match = DATE_FOLDER_PATTERN.match(name.strip())
    if not match:
        return None

    year = int(match.group(1))
    month = MONTHS.get(match.group(2).lower())
    day = int(match.group(3))
    if not month:
        return None
    return year, month, day


def date_from_path(path: Path, root: Path) -> tuple[int, int, int] | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None

    for part in reversed(relative.parts[:-1]):
        parsed = parse_date_folder(part)
        if parsed:
            return parsed
    return None


_DIGIT_RUN_PATTERN = re.compile(r"(\d+)")


def _natural_sort_key(text: str) -> tuple:
    """Splits text into alternating non-digit/digit chunks so an embedded
    number sorts by its integer value, not as a string. Plain string sorting
    put "Page (24).jpg" before "Page (4).jpg" before "Page (5).jpg" -- '2' < '4'
    < '5' as characters -- so a real folder of Page (4)/(5)/(24)/(32) processed
    in the order 24, 32, 4, 5 instead of 4, 5, 24, 32.

    Every chunk becomes a (type_marker, value) pair -- (0, "page ") for text,
    (1, 24) for a digit run -- rather than a bare int or str. Comparing two
    natural keys compares these pairs position by position; the leading
    int marker (0 or 1) always resolves a type mismatch before Python would
    otherwise try to compare an int chunk against a str chunk directly, which
    raises TypeError. Without this, one filename with a numeric run at a
    position where another filename has a text run (a very plausible mix in
    a real source folder) would crash the whole batch run's file listing
    instead of just sorting oddly.
    """
    return tuple(
        (1, int(chunk)) if chunk.isdigit() else (0, chunk.lower())
        for chunk in _DIGIT_RUN_PATTERN.split(text)
        if chunk
    )


def image_sort_key(path: Path, root: Path) -> tuple[object, ...]:
    relative = path.relative_to(root)
    parsed_date = date_from_path(path, root)
    if parsed_date:
        return (0, parsed_date, _natural_sort_key(str(relative.parent)), _natural_sort_key(path.name))
    return (1, _natural_sort_key(str(relative.parent)), _natural_sort_key(path.name))


def display_name(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _path_is_or_contains_symlink(path: Path, root: Path) -> bool:
    """True if `path` itself, or any directory between it and `root`
    (exclusive), is a symlink. `Path.is_symlink()` alone only checks the
    final path component -- a file reached through a symlinked *directory*
    (source_folder/aliased_subdir/page.jpg, say) would otherwise pass that
    check even though part of the path taken to reach it isn't really
    inside the folder the user selected."""
    current = path
    while current != root:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            break
        current = parent
    return False


def validate_batch_source_file(image_path: Path, source_root: Path) -> None:
    """Rejects a discovered batch source file that is (or is reached
    through) a symlink, or that exceeds MAX_BATCH_IMAGE_BYTES -- see
    reviews/CODEX_REVIEW.md finding M-1 / reviews/HUMAN_DECISIONS.md. Raises RuntimeError,
    which run_batch()'s existing per-image try/except turns into one failed
    image rather than aborting the batch or, for the size check, reading an
    unbounded amount of data into memory before ever finding out it was too
    large (the size check runs before anything reads the file's bytes)."""
    if _path_is_or_contains_symlink(image_path, source_root):
        raise RuntimeError(
            f"{image_path.name} is a symlink (or is reached through one) -- refusing to follow it. "
            "Source images must be real files inside the selected source folder, not links to files "
            "elsewhere on this machine."
        )
    size = image_path.stat().st_size
    if size > MAX_BATCH_IMAGE_BYTES:
        raise RuntimeError(
            f"{image_path.name} is {size / 1_000_000:.1f} MB, over the "
            f"{MAX_BATCH_IMAGE_BYTES // 1_000_000} MB per-file limit -- skipping."
        )


def source_files(folder: Path, extensions: Iterable[str], reverse_order: bool = False) -> list[Path]:
    if not folder.exists():
        raise FileNotFoundError(f"Source folder does not exist: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Source folder is not a directory: {folder}")

    allowed_extensions = {extension.lower() for extension in extensions}
    files = sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in allowed_extensions
        ),
        key=lambda path: image_sort_key(path, folder),
    )
    if reverse_order:
        files.reverse()
    return files


def extensions_for_file_type(file_type: str) -> frozenset[str]:
    try:
        return FILE_TYPE_EXTENSIONS[file_type]
    except KeyError as exc:
        raise RuntimeError("Select JPEG or PNG as the source file type.") from exc


def count_source_files_by_type(folder: Path) -> dict[str, int]:
    if not folder.exists():
        raise FileNotFoundError(f"Source folder does not exist: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Source folder is not a directory: {folder}")

    counts = {file_type: 0 for file_type in FILE_TYPE_EXTENSIONS}
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        for file_type, extensions in FILE_TYPE_EXTENSIONS.items():
            if suffix in extensions:
                counts[file_type] += 1
                break
    return counts


def default_output_file(project_dir: Path) -> Path:
    # Microsecond precision, not just seconds -- defense in depth alongside
    # the atomic run-slot reservation in app.py's /run and /test-mode/run
    # handlers, which is what actually prevents two overlapping jobs from
    # ever computing this stamp at the same moment in the first place.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return project_dir / "outputs" / f"transcription-{stamp}.md"


@dataclass
class LLMClient:
    provider: str
    gemini: genai.Client | None = None
    claude: anthropic.Anthropic | None = None


def make_client(
    project_dir: Path,
    model: str,
    api_key_override: str | None = None,
    timeout_seconds: float | None = None,
) -> LLMClient:
    # run_batch() passes BATCH_REQUEST_TIMEOUT_SECONDS (a generous per-call
    # bound, not a per-batch one -- see its own comment) since a real batch
    # run is a long-lived background job with its own per-image progress log
    # and can tolerate a genuinely slow-but-working image; it just can't
    # tolerate a connection that never returns at all, since Stop only takes
    # effect between images. Prompt Builder's Preflight Test (app.py) passes
    # its own, much tighter value, since that call blocks a single foreground
    # request with no progress log to fall back on -- see
    # preflight_test_prompt_builder(). Any other caller that omits
    # timeout_seconds entirely (e.g. validate_api_key()'s quick key check)
    # gets the SDK's own default behavior.
    provider = provider_for_model(model)
    if provider == "claude":
        key = (api_key_override or "").strip() or claude_api_key(project_dir)
        claude_kwargs: dict[str, object] = {"api_key": key}
        if timeout_seconds is not None:
            claude_kwargs["timeout"] = timeout_seconds
        return LLMClient(provider="claude", claude=anthropic.Anthropic(**claude_kwargs))
    key = (api_key_override or "").strip() or api_key(project_dir)
    gemini_kwargs: dict[str, object] = {"api_key": key}
    if timeout_seconds is not None:
        gemini_kwargs["http_options"] = types.HttpOptions(timeout=int(timeout_seconds * 1000))
    return LLMClient(provider="gemini", gemini=genai.Client(**gemini_kwargs))


def validate_api_key(
    project_dir: Path,
    model: str,
    api_key_override: str | None = None,
    timeout_seconds: float | None = KEY_CHECK_TIMEOUT_SECONDS,
) -> None:
    # Always bounded (KEY_CHECK_TIMEOUT_SECONDS by default; Prompt Builder's
    # Preflight Test passes its own PREFLIGHT_TIMEOUT_SECONDS). The old
    # "None = SDK default" reasoning assumed Stop could interrupt this call, but
    # Stop is only checked between calls, so an unbounded key check could leave
    # the UI on "Checking API key..." for the SDK's full default duration
    # (reviews/CODEX_REVIEW.md M-3). A stall is reported as a plain, non-retried error.
    client = make_client(project_dir, model, api_key_override, timeout_seconds=timeout_seconds)
    try:
        if client.provider == "claude":
            client.claude.messages.create(
                model=model,
                max_tokens=4,
                messages=[{"role": "user", "content": "Reply with OK."}],
            )
            return
        client.gemini.models.generate_content(
            model=model,
            contents="Reply with OK.",
            config=types.GenerateContentConfig(max_output_tokens=4),
        )
    except (httpx.TimeoutException, anthropic.APITimeoutError) as exc:
        raise RuntimeError(
            f"The API key check did not finish within {int(timeout_seconds or 0)}s -- the connection to "
            f"{'Anthropic' if client.provider == 'claude' else 'Google AI'} appears to be stalled. "
            "Check your network connection and try again."
        ) from exc


# --- Provider transient-failure handling ------------------------------------
# A 429 (rate limit) or 5xx (provider-side overload/outage, e.g. Gemini's own
# "This model is currently experiencing high demand... Please try again
# later.") is a transient failure worth a short retry, not an immediate
# abort -- both are common on the sequential per-image calls run_batch()
# makes and usually clear up within seconds to a couple of minutes. Shared by
# validate_api_key_with_retry()/transcribe_image_with_retry() below and by
# xls_conversion/ai_parser.py's call_ai_json(), which imports these from here
# rather than keeping its own duplicate copy.
MAX_TRANSIENT_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 1.0
RETRY_MAX_DELAY_SECONDS = 20.0


def _is_transient_provider_error(exc: Exception) -> bool:
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    if isinstance(exc, genai_errors.APIError):
        return exc.code == 429 or exc.code >= 500
    return False


def _is_cached_content_not_found_error(exc: Exception) -> bool:
    """True when a Gemini call failed because the explicit context cache
    passed as cached_content (see create_gemini_prompt_cache()) has expired
    or been deleted server-side -- a real 403 the API returns once the
    cache's name stops resolving ('CachedContent not found (or permission
    denied)'), not a genuine API-key permission problem. A batch that runs
    longer than the cache's 1-hour ttl (run_batch()/parse_generic() reuse one
    cache's name across every sequential per-image call) will hit this on
    whichever call is in flight when the cache lapses, and every call after
    it unless the caller recovers. Distinguished from any other 403 (a
    genuinely revoked/invalid API key, for instance) so only this specific,
    recoverable case triggers the no-cache fallback in
    _generate_content_with_cache_fallback() below -- a real permission error
    should still surface as a hard failure, not be silently retried."""
    return isinstance(exc, genai_errors.APIError) and exc.code == 403 and "cachedcontent" in str(exc).lower()


def _generate_content_with_cache_fallback(
    client: genai.Client,
    model: str,
    contents: object,
    config_with_cache: dict[str, object],
    config_without_cache: dict[str, object],
) -> object:
    """Shared by _transcribe_image_gemini() and xls_conversion/ai_parser.py's
    call_gemini_json() -- both build two variants of the same call's config
    (one referencing an explicit prompt cache, one sending the system prompt
    fresh) and only differ in exactly which config keys they set. Tries the
    cache first (cheaper); on the specific "cache no longer exists" error,
    retries the same call once with the prompt sent fresh instead of letting
    a mid-batch cache expiry fail this call (and, without this, every
    subsequent call in the same loop, since callers otherwise keep reusing
    the same now-dead cache name). Any other exception -- including a
    second failure on the fallback attempt itself -- propagates normally.
    Prints unconditionally (not gated behind a progress callback) rather than
    threading one through transcribe_image()/transcribe_image_with_retry()
    just for this rare event -- matches the existing unconditional
    print(f"[xls-conversion] ...") diagnostics in call_gemini_json() below."""
    try:
        return client.models.generate_content(
            model=model, contents=contents, config=types.GenerateContentConfig(**config_with_cache)
        )
    except Exception as exc:
        if not _is_cached_content_not_found_error(exc):
            raise
        print(
            f"[gemini-cache] Prompt cache no longer available ({exc}); "
            "retrying this request with the system prompt sent directly."
        )
        usage_ledger.event("cache_fallback", reason=str(exc)[:200])
        return client.models.generate_content(
            model=model, contents=contents, config=types.GenerateContentConfig(**config_without_cache)
        )


def _provider_error_status(exc: Exception) -> int | None:
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code
    if isinstance(exc, genai_errors.APIError):
        return exc.code
    return None


def _with_transient_retry(call: Callable[[], object], progress: Callable[[str], None] | None = None) -> object:
    attempt = 0
    while True:
        try:
            return call()
        except Exception as exc:
            if not _is_transient_provider_error(exc) or attempt >= MAX_TRANSIENT_RETRIES:
                raise
            delay = min(RETRY_BASE_DELAY_SECONDS * (2**attempt), RETRY_MAX_DELAY_SECONDS)
            delay += random.uniform(0, delay * 0.25)
            usage_ledger.event(
                "transient_retry", attempt_number=attempt + 1, status=_provider_error_status(exc), error=str(exc)[:200]
            )
            if progress:
                progress(
                    f"Provider reported a temporary error ({exc}); "
                    f"retrying ({attempt + 1}/{MAX_TRANSIENT_RETRIES}) in {delay:.1f}s..."
                )
            time.sleep(delay)
            attempt += 1


def validate_api_key_with_retry(
    project_dir: Path,
    model: str,
    api_key_override: str | None = None,
    progress: Callable[[str], None] | None = None,
    timeout_seconds: float | None = KEY_CHECK_TIMEOUT_SECONDS,
) -> None:
    _with_transient_retry(
        lambda: validate_api_key(project_dir, model, api_key_override, timeout_seconds=timeout_seconds),
        progress=progress,
    )


def _is_auth_error(exc: Exception, status: int | None) -> bool:
    """A key the provider flatly refuses to recognize -- Anthropic's own 401
    ("invalid x-api-key"), and Gemini's equivalent, which Google reports as a
    400 with an "API key not valid" message rather than a real 401 (Gemini's
    API has no separate auth-error status code the way Anthropic's does)."""
    if status == 401:
        return True
    if status == 400 and isinstance(exc, genai_errors.APIError):
        return "api key not valid" in str(exc).lower()
    return False


def humanize_provider_error(exc: Exception, model: str) -> str:
    """Rewrite a known failure shape (bad API key, no access to this model,
    rate-limited, provider outage) into a message a non-technical user can
    actually act on -- names the model and the provider account setting
    responsible, and says plainly when it's the provider's own service or
    key and not this app. Anything not recognized as one of these specific
    shapes passes through as str(exc) unchanged, so a real, unanticipated
    error is never hidden behind a generic message."""
    status = _provider_error_status(exc)
    provider = provider_for_model(model)
    provider_name = "Anthropic" if provider == "claude" else "Google AI"
    console_hint = (
        "console.anthropic.com -> Settings -> API Keys"
        if provider == "claude"
        else "aistudio.google.com/apikey"
    )
    if _is_auth_error(exc, status):
        return (
            f'{provider_name} rejected the API key used for "{model}" (HTTP {status}, invalid API '
            "key) -- this is the provider's own server saying it doesn't recognize the key, not a "
            "bug in this app. Double-check you copied the entire key with no extra spaces or line "
            f"breaks, that it hasn't been regenerated or revoked since you copied it ({console_hint}), "
            "and that it's actually a key for this provider (a Claude key won't work for a Gemini "
            f"model, or the reverse). (Original error: {exc})"
        )
    if status == 403:
        return (
            f'{provider_name} accepted the API key but denied it access to "{model}" (HTTP 403, '
            "permission denied). This usually means the key's account doesn't have this specific "
            "model enabled, has no billing/payment method set up, or has hit an organization-level "
            f"restriction -- check the key's account settings at {console_hint}, not this app. "
            f"(Original error: {exc})"
        )
    if not _is_transient_provider_error(exc):
        return str(exc)
    if status == 429:
        return (
            f'"{model}" is rate-limiting this API key right now (HTTP 429, too many requests). '
            f"This already retried {MAX_TRANSIENT_RETRIES} times with a short delay and is still "
            "being limited -- wait a bit and try again, or switch to a different model for now. "
            f"(Original error: {exc})"
        )
    return (
        f'"{model}" is temporarily unavailable on the provider\'s own servers (HTTP {status or "5xx"}) '
        "-- this is not a problem with your API key or this app. It already retried "
        f"{MAX_TRANSIENT_RETRIES} times with a short delay before giving up. This is usually "
        "temporary: wait a few minutes and try again, or switch to a different model for now. "
        f"(Original error: {exc})"
    )


# A response cut off mid-generation by the provider's own output-token cap is
# worse than an honest [illegible] -- it drops content with no marker at all,
# and (unlike a max_tokens error that aborts the image outright) a genuinely
# large image can have several real entries land after the cutoff, silently
# missing from the DOCX. Keep whatever text did come back -- it's still real,
# usable model output up to that point -- but append a marker that can't be
# missed, matching this app's existing convention of flagging a gap rather
# than hiding it (see the Uncertainty Protocol's [illegible]/[damaged]).
_TRUNCATION_NOTICE = (
    "\n\n[TRUNCATED: this image's response hit the model's output token limit before "
    "finishing. Everything above is genuine model output, but later entries on this image "
    "may be missing entirely. Re-run this image on its own to try to recover the rest.]"
)
# Appended instead of the generic notice above when transcribe_image_with_retry()
# already tried and failed to recover the rest itself (see its own comment) --
# telling the user to just "re-run this image" would be misleading when that's
# exactly what already happened, automatically, with no improvement.
_TRUNCATION_NOTICE_AFTER_RETRY = (
    "\n\n[TRUNCATED: this image's response hit the model's output token limit before "
    "finishing, even after an automatic retry with a lower thinking budget. Everything "
    "above is genuine model output, but later entries on this image may be missing "
    "entirely. This image's content likely genuinely exceeds the model's output "
    "capacity -- consider splitting it into two images (e.g. by page) and re-running.]"
)


# Model generations that expose ThinkingLevel (SEC-4-02): a prefix tuple, not a bare
# "gemini-3" check, so a newer generation keeps the cap + MAX_TOKENS retry. Add the
# next generation's prefix here when it ships.
_CAPPABLE_GEMINI_PREFIXES = ("gemini-3", "gemini-4")


def _gemini_thinking_is_cappable(model: str) -> bool:
    """True when max_thinking_level actually does something for this model --
    see _transcribe_image_gemini()'s own thinking_config branch, which this
    mirrors exactly. Only gemini-3.x and newer models expose ThinkingLevel at all,
    which matters to transcribe_image_with_retry()'s truncation retry below:
    no point spending a whole extra API call capping a knob that has no
    effect for gemini-2.5-pro or Claude."""
    return (
        model.startswith(_CAPPABLE_GEMINI_PREFIXES)
        and hasattr(types, "ThinkingConfig")
        and hasattr(types, "ThinkingLevel")
    )


def _transcribe_image_gemini(
    client: genai.Client,
    data: bytes,
    mime_type: str,
    system_prompt: str,
    model: str,
    include_thoughts: bool,
    max_thinking_level: str | None = None,
    cached_content: str | None = None,
    page_images: tuple[bytes, bytes] | None = None,
) -> str:
    # cached_content is an explicit Gemini context cache's resource name (see
    # create_gemini_prompt_cache()) holding this exact system_prompt --
    # passing both cached_content and system_instruction together is
    # rejected by the API, since the cache already carries the prompt the
    # caller would otherwise be resending, in full, on every single image in
    # a run_batch()/parse_generic() loop. A missing/expired/unsupported
    # cache (cached_content is None) falls back to today's behavior of
    # sending system_instruction fresh every call -- caching is a cost
    # optimization the batch must work correctly without, never a
    # correctness requirement. A cache that WAS created but has since expired
    # or been deleted server-side (cached_content is still a truthy name, but
    # no longer resolves) is handled by _generate_content_with_cache_fallback()
    # below, not by this branch -- that's a mid-call failure, not something
    # knowable from cached_content's value alone.
    config_kwargs: dict[str, object] = {"cached_content": cached_content} if cached_content else {
        "system_instruction": system_prompt
    }
    config_kwargs["temperature"] = 0
    config_kwargs_no_cache: dict[str, object] = {"system_instruction": system_prompt, "temperature": 0}

    if include_thoughts and hasattr(types, "ThinkingConfig"):
        thinking_config = types.ThinkingConfig(include_thoughts=True)
        config_kwargs["thinking_config"] = thinking_config
        config_kwargs_no_cache["thinking_config"] = thinking_config
    elif max_thinking_level and _gemini_thinking_is_cappable(model):
        # A real batch run (include_thoughts False, max_thinking_level None)
        # leaves Gemini 3.x's default (uncapped) thinking budget untouched --
        # this only fires for a caller that explicitly asks for a ceiling, e.g.
        # Prompt Builder's Preflight Test, where "high" reasoning over a full
        # image plus a long system prompt can otherwise run for several
        # minutes with no feedback. See call_gemini_json() in
        # xls_conversion/ai_parser.py for the same cap on its own calls.
        level = getattr(types.ThinkingLevel, max_thinking_level, None)
        if level is not None:
            thinking_config = types.ThinkingConfig(thinking_level=level)
            config_kwargs["thinking_config"] = thinking_config
            config_kwargs_no_cache["thinking_config"] = thinking_config

    contents: list[object] = [types.Part.from_bytes(data=data, mime_type=mime_type)]
    if page_images:
        # Page zoom: full photo first, then each page's crop -- see page_zoom.py.
        contents += [types.Part.from_bytes(data=crop, mime_type="image/jpeg") for crop in page_images]
        contents.append(USER_INSTRUCTION + page_zoom.PAGE_ZOOM_INSTRUCTION)
    else:
        contents.append(USER_INSTRUCTION)
    started = time.monotonic()
    if cached_content:
        response = _generate_content_with_cache_fallback(
            client, model, contents, config_kwargs, config_kwargs_no_cache
        )
    else:
        response = client.models.generate_content(
            model=model, contents=contents, config=types.GenerateContentConfig(**config_kwargs)
        )
    text = response.text or ""
    usage_ledger.record_gemini(
        response,
        model=model,
        seconds=time.monotonic() - started,
        cache_expected=bool(cached_content),
        text_chars=len(text),
    )
    candidates = getattr(response, "candidates", None) or []
    finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    if not text.strip():
        # A safety/recitation block or a thoughts-only reply comes back as "" --
        # saving that as a finished record would hide a missing page. Raising
        # sends it through run_batch()'s per-image error path instead.
        reason = getattr(finish_reason, "name", None) or str(finish_reason or "no candidates")
        raise RuntimeError(f"The model returned no transcription text (finish reason: {reason}).")
    if finish_reason == types.FinishReason.MAX_TOKENS:
        text += _TRUNCATION_NOTICE
    return text


def claude_system_param(system_prompt: str, use_prompt_cache: bool) -> str | list[dict[str, object]]:
    """The `system` value for a Claude call, with a cache breakpoint on the
    system prompt itself when caching is wanted.

    Unlike Gemini's cached_content (an object created once and reused by
    name), Claude's prompt caching is a per-call marker with no object to
    create or clean up: later calls with an identical prefix up to the marker
    read it from cache. The marker must sit on the system block, not the
    request's top-level `cache_control` -- that automatic form caches up to
    the LAST block, i.e. after the per-image content, so every image wrote a
    fresh cache entry and none was ever read (found 2026-09-23 in the usage
    ledger: ~17.8k cache-write tokens per image, zero cache reads). Only
    requested by callers looping over one system_prompt (run_batch(),
    parse_generic()/preflight_generic()); one-off callers such as Preflight
    Test have no repeated calls to amortize a cache write against.
    """
    if not use_prompt_cache:
        return system_prompt
    return [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]


def _transcribe_image_claude(
    client: anthropic.Anthropic,
    data: bytes,
    mime_type: str,
    system_prompt: str,
    model: str,
    use_prompt_cache: bool = False,
) -> str:
    encoded = base64.standard_b64encode(data).decode("utf-8")
    source_block = {
        "type": "image",
        "source": {"type": "base64", "media_type": mime_type, "data": encoded},
    }
    # Streaming, not a plain (non-streaming) messages.create() call. This used
    # to be non-streaming with max_tokens capped at 16000 -- raised once
    # already from 8192 after truncating mid-entry, with a comment noting
    # 16000 was "the documented safe ceiling for a non-streaming call; going
    # higher risks the SDK's own HTTP timeout." That ceiling was hit for real:
    # a dense marriage-register image (several entries, each with a full
    # native transcription, translation, and notes) still exceeded 16000 and
    # got cut off mid-entry. Per Anthropic's own SDK guidance, a non-streaming
    # request is capped near 16000 specifically to stay under the SDK's HTTP
    # timeout -- streaming removes that constraint entirely, which is why
    # max_tokens can now go to 64000 instead of trying to guess a higher safe
    # non-streaming number.
    started = time.monotonic()
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        # This SDK's Messages API has no temperature knob (Gemini's temperature=0
        # equivalent doesn't exist here) -- "high" effort is the closest available
        # lever for careful, consistent transcription output.
        output_config={"effort": "high"},
        system=claude_system_param(system_prompt, use_prompt_cache),
        messages=[
            {
                "role": "user",
                "content": [source_block, {"type": "text", "text": USER_INSTRUCTION}],
            }
        ],
    ) as stream:
        response = stream.get_final_message()
    text = "".join(block.text for block in response.content if block.type == "text")
    usage_ledger.record_claude(
        response,
        model=model,
        seconds=time.monotonic() - started,
        cache_expected=use_prompt_cache,
        text_chars=len(text),
    )
    if response.stop_reason == "max_tokens":
        text += _TRUNCATION_NOTICE
    return text


def transcribe_image(
    client: LLMClient,
    image_path: Path,
    system_prompt: str,
    model: str,
    include_thoughts: bool = False,
    max_thinking_level: str | None = None,
    cached_content: str | None = None,
    use_prompt_cache: bool = False,
    zoom_pages: bool = False,
    progress: Callable[[str], None] | None = None,
) -> str:
    data = image_path.read_bytes()
    # Detected from the file's own leading bytes, not its extension -- same
    # sniff_file_type() the single-upload paths (Prompt Builder's Preflight
    # Test, XLS Conversion's DOCX upload) already use, and the same reasoning:
    # a batch source folder is selected by the user, not vetted file-by-file,
    # so a mislabeled or renamed file (a real ".jpg" that's actually a screenshot
    # someone renamed, a stray non-image file matching the extension filter by
    # accident) would otherwise be sent to the AI provider tagged with a MIME
    # type that doesn't match its real content, or -- for anything that isn't
    # even a JPEG/PNG at all -- sent as arbitrary unvalidated bytes. This
    # rejects it as a clean per-image failure (see run_batch()'s own per-image
    # try/except) instead.
    detected_type = sniff_file_type(data)
    if detected_type is None:
        raise RuntimeError(
            f"{image_path.name} does not look like a JPEG or PNG file (checked its content, "
            "not just its extension) -- skipping."
        )
    mime_type = FILE_TYPE_MIME[detected_type]
    if client.provider == "claude":
        return _transcribe_image_claude(
            client.claude, data, mime_type, system_prompt, model, use_prompt_cache
        )
    page_images = None
    if zoom_pages and detected_type in ("jpeg", "png"):
        page_images = page_zoom.page_crops(data)
        if page_images is None and progress:
            progress(f"{image_path.name}: no clear gutter between two pages found; sent the full photo only.")
    return _transcribe_image_gemini(
        client.gemini,
        data,
        mime_type,
        system_prompt,
        model,
        include_thoughts,
        max_thinking_level,
        cached_content,
        page_images,
    )


def transcribe_image_with_retry(
    client: LLMClient,
    image_path: Path,
    system_prompt: str,
    model: str,
    include_thoughts: bool = False,
    max_thinking_level: str | None = None,
    progress: Callable[[str], None] | None = None,
    cached_content: str | None = None,
    use_prompt_cache: bool = False,
    zoom_pages: bool = False,
) -> str:
    text = _with_transient_retry(
        lambda: transcribe_image(
            client,
            image_path,
            system_prompt,
            model,
            include_thoughts,
            max_thinking_level,
            cached_content,
            use_prompt_cache,
            zoom_pages=zoom_pages,
            progress=progress,
        ),
        progress=progress,
    )
    if not text.endswith(_TRUNCATION_NOTICE):
        return text
    usage_ledger.event("truncated_output", provider=client.provider)

    # A truncation notice means finish_reason/stop_reason came back as
    # MAX_TOKENS (see _transcribe_image_gemini()/_transcribe_image_claude()
    # above) -- the response was cut off mid-generation, not just genuinely
    # long. For gemini-3.x specifically, this is very often the model's
    # *thinking* budget (uncapped by default on this real-batch path -- see
    # _gemini_thinking_is_cappable()'s own comment) eating most of the
    # shared output-token pool before it finishes writing the actual
    # transcription, especially on a dense or two-page source image. Retry
    # once with thinking capped low, trading some reasoning depth for
    # headroom to actually finish the response -- worth it since a
    # completed transcription beats a partial one with entries silently
    # missing. Not attempted for Claude (no shared thinking/output budget
    # here -- see _transcribe_image_claude(), which never sets a thinking
    # config) or for a model that doesn't expose ThinkingLevel at all
    # (_gemini_thinking_is_cappable()), since capping a knob with no effect
    # would just spend a second API call for nothing.
    if (
        client.provider != "gemini"
        or not _gemini_thinking_is_cappable(model)
        or (max_thinking_level or "").upper() in ("LOW", "MINIMAL")
    ):
        return text

    if progress:
        progress(
            f"{image_path.name}: output was truncated by the model's token limit; "
            "retrying once with a lower thinking budget to leave more room for the "
            "transcription itself..."
        )
    with usage_ledger.attempt_context("truncation_retry"):
        retry_text = _with_transient_retry(
            lambda: transcribe_image(
                client,
                image_path,
                system_prompt,
                model,
                include_thoughts,
                "LOW",
                cached_content,
                use_prompt_cache,
                zoom_pages=zoom_pages,
            ),
            progress=progress,
        )
    usage_ledger.event("truncation_retry_result", resolved=not retry_text.endswith(_TRUNCATION_NOTICE))
    if not retry_text.endswith(_TRUNCATION_NOTICE):
        if progress:
            progress(f"{image_path.name}: retry with a lower thinking budget finished without truncation.")
        return retry_text
    if progress:
        progress(
            f"{image_path.name}: retry with a lower thinking budget still hit the output token "
            "limit; keeping the original result."
        )
    return text[: -len(_TRUNCATION_NOTICE)] + _TRUNCATION_NOTICE_AFTER_RETRY


# Explicit Gemini context caching for a batch run's fixed system prompt --
# see _transcribe_image_gemini()'s own cached_content comment for how the
# per-call side works. This pair owns the cache's lifecycle: create once
# before a run_batch()/parse_generic()-style loop starts, reuse its name on
# every call in that loop, delete it once the loop ends. Claude needs
# neither function -- its own caching is a stateless per-call flag, see
# _transcribe_image_claude()'s use_prompt_cache.
def create_gemini_prompt_cache(
    client: genai.Client,
    model: str,
    system_prompt: str,
    progress: Callable[[str], None] | None = None,
) -> str | None:
    """Returns the new cache's resource name on success, or None if caching
    isn't available right now for this model/prompt (a preview model that
    doesn't yet support explicit caching, a system_prompt too short to meet
    the provider's minimum cacheable-token floor, a transient API error,
    etc.). Callers must treat None as "fall back to sending the system
    prompt on every call" (today's behavior), never as a fatal error --
    prompt caching is a cost optimization the batch must keep working
    correctly without."""
    try:
        cache = client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                system_instruction=system_prompt,
                # 1 hour comfortably covers the gap between consecutive
                # per-image calls in a real batch; a batch that runs longer
                # than this still completes correctly -- transcribe_image()
                # falls back to sending system_prompt directly once the
                # cache's name stops resolving, it just stops billing at the
                # cached rate for the remainder.
                ttl="3600s",
            ),
        )
    except Exception as exc:
        usage_ledger.event("cache_unavailable", reason=str(exc)[:200])
        if progress:
            progress(f"Prompt caching unavailable for {model} ({exc}); continuing without it.")
        return None
    usage_ledger.event(
        "cache_created",
        cached_tokens=getattr(getattr(cache, "usage_metadata", None), "total_token_count", None),
        ttl_seconds=3600,
    )
    return cache.name


def delete_gemini_prompt_cache(client: genai.Client, cache_name: str) -> None:
    """Best-effort cleanup once a run's loop is done with the cache. Silently
    ignored on failure (network blip, already expired) -- an unreleased
    cache still self-expires via its own ttl, so this is tidiness, not a
    correctness requirement, and must never turn a successful batch run into
    a reported failure over a cleanup call."""
    try:
        client.caches.delete(name=cache_name)
    except Exception:
        pass


def collapse_source_line_breaks(text: str) -> str:
    paragraphs: list[str] = []
    current: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue

        if line.endswith(":") and current:
            paragraphs.append(" ".join(current))
            current = [line]
            continue

        current.append(line)

    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs)


def strip_model_record_headers(text: str) -> str:
    lines = text.splitlines()
    while lines and re.match(r"^\s*-{3,}\s*START OF RECORD:.*-{3,}\s*$", lines[0], re.IGNORECASE):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines)


# The two fixed continuation notes the prompt tells the model to write (see
# static/prompt-builder.js). The app upgrades them to a preset note that names
# the neighbouring image's record, so a reader of the DOCX knows where to look.
# XLS Conversion (xls_conversion/ai_parser.py's _says_continues_on_next/
# _says_continues_from_previous, block_ends_with_open_entry(),
# split_leading_continuation()) recognises a note by "continu..." plus "next
# image"/"previous image" -- keep both phrases in the preset wording below.
_CONTINUES_ON_NEXT_RE = re.compile(
    r"Entry\s+(?:appears\s+to\s+)?continu\w*\s+on\s+the\s+next\s+(?:image|page)\.?", re.IGNORECASE
)
_CONTINUES_FROM_PREVIOUS_RE = re.compile(
    r"Entry\s+(?:appears\s+to\s+)?continu\w*\s+from\s+the\s+(?:previous|preceding|prior)\s+(?:image|page)\.?",
    re.IGNORECASE,
)


def continues_on_next_note(next_name: str | None) -> str:
    where = (
        f"the rest of this entry is in the record for {next_name}"
        if next_name
        else "the next image is not part of this run"
    )
    return f"ENTRY CONTINUES ON THE NEXT IMAGE -- {where}."


def continues_from_previous_note(previous_name: str | None) -> str:
    where = (
        f"the beginning of this entry is in the record for {previous_name}"
        if previous_name
        else "the previous image is not part of this run"
    )
    return f"ENTRY CONTINUES FROM THE PREVIOUS IMAGE -- {where}."


_NOTES_LINE_RE = re.compile(r"^\s*Notes\s*:", re.IGNORECASE)
_TRANSCRIPTION_LABEL_LINE_RE = re.compile(r"^\s*(?:.+?\s+Transcription|Trascrizione in .+?)\s*:", re.IGNORECASE)


def _last_entry_notes_line(lines: list[str]) -> int | None:
    """Index of the last Notes line when it belongs to the block's last entry
    (the last transcription label comes right after it), else None. Mirrors
    xls_conversion/ai_parser.py's block_ends_with_open_entry(): a stray flag on
    an earlier entry must not mark the whole record as continuing."""
    notes_at = [i for i, line in enumerate(lines) if _NOTES_LINE_RE.match(line)]
    labels_at = [i for i, line in enumerate(lines) if _TRANSCRIPTION_LABEL_LINE_RE.match(line)]
    if not notes_at or not labels_at:
        return None
    following = [i for i in labels_at if i > notes_at[-1]]
    if following and following[0] == labels_at[-1]:
        return notes_at[-1]
    return None


def standardize_continuation_notes(text: str, next_name: str | None, previous_name: str | None) -> str:
    """Turn the model's two fixed continuation sentences into the preset notes.

    "Continues from the previous image" stays where the model put it: in the
    Notes line at the top of the record, right under the START OF RECORD line.
    "Continues on the next image" is moved out of the last entry's Notes line
    to the very end of the record, so both continuation notes sit at the
    boundary between the two images. Anything else in the Notes line is kept."""
    text = _CONTINUES_FROM_PREVIOUS_RE.sub(lambda _m: continues_from_previous_note(previous_name), text)
    lines = text.split("\n")
    notes_at = _last_entry_notes_line(lines)
    if notes_at is None or not _CONTINUES_ON_NEXT_RE.search(lines[notes_at]):
        return _CONTINUES_ON_NEXT_RE.sub(lambda _m: continues_on_next_note(next_name), text)
    remaining = _CONTINUES_ON_NEXT_RE.sub("", lines[notes_at])
    if re.fullmatch(r"\s*Notes\s*:[\s.;,]*", remaining, re.IGNORECASE):
        del lines[notes_at]
        if notes_at < len(lines) and not lines[notes_at].strip():
            del lines[notes_at]
    else:
        lines[notes_at] = re.sub(r"\s{2,}", " ", remaining).rstrip()
    body = _CONTINUES_ON_NEXT_RE.sub(lambda _m: continues_on_next_note(next_name), "\n".join(lines))
    return body.rstrip() + "\n\nNotes: " + continues_on_next_note(next_name)


def physical_neighbors(names: list[str], index: int, reverse_order: bool) -> tuple[str | None, str | None]:
    """(next, previous) image names for names[index] in reading order.
    `names` is in processing order, which a reverse-order run flips."""
    step = -1 if reverse_order else 1

    def at(position: int) -> str | None:
        return names[position] if 0 <= position < len(names) else None

    return at(index + step), at(index - step)


def render_entry(filename: str, text: str, next_name: str | None = None, previous_name: str | None = None) -> str:
    clean_text = standardize_continuation_notes(strip_model_record_headers(text), next_name, previous_name)
    clean_text = collapse_source_line_breaks(clean_text)
    return f"\n\n--- START OF RECORD: {filename} ---\n\n{clean_text}\n"


def run_batch(
    config: TranscriptionConfig,
    project_dir: Path,
    progress: Callable[[str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> list[ImageResult]:
    prompt = config.system_prompt or config.prompt_file.read_text(encoding="utf-8")
    files = source_files(config.image_folder, config.source_extensions, config.reverse_order)
    config.output_file.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        if progress:
            progress(message)

    log(f"Found {len(files)} source file(s).")
    client = make_client(
        project_dir, config.model, config.api_key_override, timeout_seconds=BATCH_REQUEST_TIMEOUT_SECONDS
    )
    results: list[ImageResult] = []
    ledger_run = usage_ledger.start_run(
        mode="regular",
        stage="transcribe",
        provider=client.provider,
        model=config.model,
        system_prompt=prompt,
        image_count=len(files),
        profile_id=config.profile_id,
        profile_label=config.profile_label,
        reverse_order=config.reverse_order,
    )
    ledger_token = usage_ledger.activate(ledger_run)

    # The same system prompt (often several thousand tokens -- worked
    # examples, a name lexicon, etc.) is resent in full on every single
    # image in this loop. Claude's caching is a stateless per-call flag, so
    # it's always requested for a real multi-image run. Gemini needs an
    # explicit cache object created up front and reused by name; only
    # created when there's actually more than one image to amortize its
    # creation cost against, and always cleaned up afterward regardless of
    # how the loop ends (Stop, an exception, or normal completion).
    use_prompt_cache = client.provider == "claude" and len(files) > 1
    zoom_pages = config.zoom_pages and client.provider == "gemini"
    if zoom_pages:
        log("Page zoom is on: each two-page photo is sent with a crop of each page.")
    elif config.zoom_pages:
        log("Page zoom only applies to Gemini models; sending full photos for this run.")
    gemini_cache_name: str | None = None
    if client.provider == "gemini" and len(files) > 1:
        gemini_cache_name = create_gemini_prompt_cache(client.gemini, config.model, prompt, progress=log)
        if gemini_cache_name:
            log("Prompt cache created for this run's system prompt.")

    try:
        with config.output_file.open("w", encoding="utf-8") as output:
            output.write(f"# Transcription Output\n\nSource folder: {config.image_folder}\n")

            names = [display_name(path, config.image_folder) for path in files]
            for index, image_path in enumerate(files, start=1):
                if cancel_requested and cancel_requested():
                    log("Stopped before next image.")
                    break

                name = names[index - 1]
                next_name, previous_name = physical_neighbors(names, index - 1, config.reverse_order)
                log(f"[{index}/{len(files)}] Processing {name}")
                image_started = time.monotonic()
                try:
                    validate_batch_source_file(image_path, config.image_folder)
                    with usage_ledger.image_context(name):
                        text = transcribe_image_with_retry(
                            client=client,
                            image_path=image_path,
                            system_prompt=prompt,
                            model=config.model,
                            include_thoughts=config.include_thoughts,
                            progress=log,
                            cached_content=gemini_cache_name,
                            use_prompt_cache=use_prompt_cache,
                            zoom_pages=zoom_pages,
                        )
                    output.write(render_entry(name, text, next_name, previous_name))
                    output.flush()
                    results.append(ImageResult(name, True, text))
                    usage_ledger.event(
                        "image_done", image=name, ok=True, seconds=round(time.monotonic() - image_started, 2)
                    )
                    log(f"Saved {name}")
                except Exception as exc:
                    usage_ledger.event(
                        "image_done",
                        image=name,
                        ok=False,
                        seconds=round(time.monotonic() - image_started, 2),
                        error=str(exc)[:200],
                    )
                    error = f"ERROR: {humanize_provider_error(exc, config.model)}"
                    output.write(render_entry(name, error, next_name, previous_name))
                    output.flush()
                    results.append(ImageResult(name, False, error))
                    log(f"Failed {name}: {humanize_provider_error(exc, config.model)}")

                if config.delay_seconds > 0 and index < len(files):
                    remaining_delay = config.delay_seconds
                    while remaining_delay > 0:
                        if cancel_requested and cancel_requested():
                            log("Stopped during delay before next image.")
                            break
                        sleep_time = min(0.25, remaining_delay)
                        time.sleep(sleep_time)
                        remaining_delay -= sleep_time
                    if cancel_requested and cancel_requested():
                        break
    finally:
        if gemini_cache_name:
            delete_gemini_prompt_cache(client.gemini, gemini_cache_name)
        usage_ledger.deactivate(ledger_token)
        usage_ledger.end_run(
            ledger_run,
            images_processed=len(results),
            failures=count_failures(results),
            stopped=bool(cancel_requested and cancel_requested()),
        )

    # Each image is read on its own, so a misread year (1799 as 1779) can't
    # be seen from inside one image; compare each entry with its neighbours.
    apply_year_check(config.output_file, config.reverse_order, log)

    if cancel_requested and cancel_requested():
        log(f"Stopped. Partial output: {config.output_file}")
    else:
        log(f"Done. Output: {config.output_file}")
    return results


def count_failures(results: Iterable[ImageResult]) -> int:
    return sum(1 for result in results if not result.ok)
