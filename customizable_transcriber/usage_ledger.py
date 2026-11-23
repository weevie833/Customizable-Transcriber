"""Per-call usage ledger: one JSON line per AI call (tokens, seconds, retries, cache
behavior), one file per run. Measurement only -- nothing here changes what is sent
to a provider or what the app produces.

Design rules:
- Disabled until app.py calls configure(); unconfigured (unit tests, ad-hoc imports)
  every function is a silent no-op.
- Never raises. A ledger failure (unwritable folder, odd SDK object) must never fail a
  transcription run, the same contract delete_gemini_prompt_cache() already follows.
- No transcription content and no API keys are written -- only counts, timings,
  image names, model names and a short hash of the system prompt.
- Deep call sites (_transcribe_image_gemini() and friends) find their run through a
  ContextVar, so no function signature or return type in core.py had to change.

Token fields are normalized across providers (see normalize_*_usage()); the provider's
own usage object is also kept verbatim under "raw" so nothing is lost if a
normalization turns out to be wrong.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from customizable_transcriber import stop_reasons

SCHEMA_VERSION = 1

_ledger_dir: Path | None = None
_current_run: ContextVar[Run | None] = ContextVar("usage_ledger_run", default=None)
_current_image: ContextVar[str | None] = ContextVar("usage_ledger_image", default=None)
_current_attempt: ContextVar[str] = ContextVar("usage_ledger_attempt", default="initial")

_TOKEN_KEYS = ("input_uncached", "input_cached", "input_cache_write", "output", "thinking")


def configure(directory: Path | None) -> None:
    """Enable the ledger, writing into `directory` (created on first run), or
    disable it with None."""
    global _ledger_dir
    _ledger_dir = Path(directory) if directory else None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Run:
    """Handle for one run's ledger file. All methods are best-effort."""

    def __init__(self, path: Path, run_id: str, stage: str, mode: str, provider: str, model: str):
        self.path = path
        self.run_id = run_id
        self.stage = stage
        self.mode = mode
        self.provider = provider
        self.model = model
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self.calls = 0
        self.tokens: Counter[str] = Counter()
        self.events: Counter[str] = Counter()
        self._write_failed = False

    def write(self, record: dict) -> None:
        try:
            line = json.dumps(record, ensure_ascii=False, default=str)
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception as exc:  # noqa: BLE001 -- ledger must never raise
            if not self._write_failed:
                self._write_failed = True
                print(f"[usage-ledger] could not write {self.path}: {exc}")


def _safe(function):
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 -- ledger must never raise
            print(f"[usage-ledger] {function.__name__} failed: {exc}")
            return None

    wrapper.__name__ = function.__name__
    wrapper.__doc__ = function.__doc__
    return wrapper


@_safe
def start_run(
    *,
    mode: str,
    stage: str,
    provider: str,
    model: str,
    system_prompt: str = "",
    image_count: int | None = None,
    profile_id: str = "",
    profile_label: str = "",
    **extra: object,
) -> Run | None:
    """mode: "regular" or "off_peak". stage: "transcribe", "xls_parse",
    "xls_preflight". Returns None (and every later call no-ops) when the ledger
    is not configured or the file can't be created."""
    if _ledger_dir is None:
        return None
    _ledger_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now(UTC).astimezone().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    run = Run(_ledger_dir / f"{run_id}-{mode}-{stage}.jsonl", run_id, stage, mode, provider, model)
    run.write(
        {
            "type": "run_start",
            "schema": SCHEMA_VERSION,
            "t": _now_iso(),
            "run_id": run_id,
            "stage": stage,
            "mode": mode,
            "provider": provider,
            "model": model,
            "profile_id": profile_id,
            "profile_label": profile_label,
            # A hash, not the prompt: lets a later report tell "same profile text" from
            # "profile was edited" without storing the prompt itself.
            "prompt_sha": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:12] if system_prompt else "",
            "prompt_chars": len(system_prompt),
            "image_count": image_count,
            **extra,
        }
    )
    return run


@_safe
def end_run(run: Run | None, **summary: object) -> None:
    if run is None:
        return
    run.write(
        {
            "type": "run_end",
            "t": _now_iso(),
            "run_id": run.run_id,
            "wall_seconds": round(time.monotonic() - run._started, 1),
            "calls": run.calls,
            "tokens": dict(run.tokens),
            "events": dict(run.events),
            **summary,
        }
    )


def activate(run: Run | None):
    return _current_run.set(run)


def deactivate(token) -> None:
    try:
        _current_run.reset(token)
    except Exception:  # noqa: BLE001, S110 -- token from another context; nothing to undo
        pass


@contextmanager
def run(**start_kwargs):
    """start_run() + activate() + end_run() as one block, for short call sites."""
    ledger_run = start_run(**start_kwargs)
    token = activate(ledger_run)
    try:
        yield ledger_run
    finally:
        deactivate(token)
        end_run(ledger_run)


@contextmanager
def image_context(name: str):
    token = _current_image.set(name)
    try:
        yield
    finally:
        _current_image.reset(token)


@contextmanager
def attempt_context(label: str):
    """Label calls made inside the block (e.g. "truncation_retry") so the report can
    separate the first pass at an image from its re-tries."""
    token = _current_attempt.set(label)
    try:
        yield
    finally:
        _current_attempt.reset(token)


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_gemini_usage(usage: object) -> dict[str, int] | None:
    """Gemini's prompt_token_count INCLUDES cached tokens (cached_content_token_count
    is a subset), so uncached = prompt - cached. thoughts_token_count is billed as
    output but reported separately from candidates_token_count."""
    if usage is None:
        return None
    prompt = _int(getattr(usage, "prompt_token_count", 0))
    cached = _int(getattr(usage, "cached_content_token_count", 0))
    return {
        "input_uncached": max(prompt - cached, 0),
        "input_cached": cached,
        "input_cache_write": 0,
        "output": _int(getattr(usage, "candidates_token_count", 0)),
        "thinking": _int(getattr(usage, "thoughts_token_count", 0)),
    }


def normalize_claude_usage(usage: object) -> dict[str, int] | None:
    """Anthropic's input_tokens EXCLUDES cache reads and cache writes (separate
    fields). Thinking tokens, when any, are already inside output_tokens -- the
    API does not report them separately, so "thinking" stays 0 here."""
    if usage is None:
        return None
    return {
        "input_uncached": _int(getattr(usage, "input_tokens", 0)),
        "input_cached": _int(getattr(usage, "cache_read_input_tokens", 0)),
        "input_cache_write": _int(getattr(usage, "cache_creation_input_tokens", 0)),
        "output": _int(getattr(usage, "output_tokens", 0)),
        "thinking": 0,
    }


def _raw(usage: object) -> dict | None:
    dump = getattr(usage, "model_dump", None)
    if dump is None:
        return None
    try:
        return dump(exclude_none=True, mode="json")
    except Exception:  # noqa: BLE001 -- raw dump is optional
        return None


def _finish_reason_text(value: object) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "name", value))


@_safe
def record_call(
    *,
    provider: str,
    model: str,
    usage: object,
    seconds: float | None = None,
    finish_reason: object = None,
    text_chars: int | None = None,
    cache_expected: bool | None = None,
    run: Run | None = None,
    image: str | None = None,
    attempt: str | None = None,
) -> None:
    """Append one call. `run`/`image`/`attempt` default to the active context."""
    target = run or _current_run.get()
    if target is None:
        return
    normalized = normalize_claude_usage(usage) if provider == "claude" else normalize_gemini_usage(usage)
    record: dict[str, object] = {
        "type": "call",
        "t": _now_iso(),
        "run_id": target.run_id,
        "stage": target.stage,
        "image": image if image is not None else _current_image.get(),
        "attempt": attempt or _current_attempt.get(),
        "provider": provider,
        "model": model,
        "usage_reported": normalized is not None,
        **(normalized or {key: None for key in _TOKEN_KEYS}),
        "finish_reason": _finish_reason_text(finish_reason),
        # complete / truncated / incomplete / blocked, classified exactly as
        # the document and run summary classify the page (CODEX_REVIEW_2.md H-5).
        "outcome": stop_reasons.classify(provider, finish_reason) if finish_reason is not None else None,
        "seconds": round(seconds, 2) if seconds is not None else None,
        "text_chars": text_chars,
        "cache_expected": cache_expected,
        "raw": _raw(usage),
    }
    target.write(record)
    target.calls += 1
    if normalized:
        target.tokens.update(normalized)


def _gemini_finish_reason(response: object) -> object:
    candidates = getattr(response, "candidates", None) or []
    return getattr(candidates[0], "finish_reason", None) if candidates else None


@_safe
def record_gemini(response: object, *, model: str, seconds: float | None, cache_expected: bool, text_chars: int) -> None:
    record_call(
        provider="gemini",
        model=model,
        usage=getattr(response, "usage_metadata", None),
        seconds=seconds,
        finish_reason=_gemini_finish_reason(response),
        text_chars=text_chars,
        cache_expected=cache_expected,
    )


@_safe
def record_claude(message: object, *, model: str, seconds: float | None, cache_expected: bool, text_chars: int) -> None:
    record_call(
        provider="claude",
        model=model,
        usage=getattr(message, "usage", None),
        seconds=seconds,
        finish_reason=getattr(message, "stop_reason", None),
        text_chars=text_chars,
        cache_expected=cache_expected,
    )


@_safe
def event(kind: str, run: Run | None = None, **fields: object) -> None:
    """Something that isn't a billed call but explains cost or time: a transient
    retry, a cache created / unavailable / expired, a truncated output, a failed image."""
    target = run or _current_run.get()
    if target is None:
        return
    target.events[kind] += 1
    target.write(
        {
            "type": "event",
            "t": _now_iso(),
            "run_id": target.run_id,
            "kind": kind,
            "image": fields.pop("image", None) or _current_image.get(),
            "attempt": _current_attempt.get(),
            **fields,
        }
    )
