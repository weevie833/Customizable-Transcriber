"""HTTP handlers for the XLS Conversion feature (the `/xls-conversion` page
and its `/api/xls-conversion/*` endpoints). Business logic lives in
xls_conversion/ai_parser.py (parse_records_with_ai()/
preflight_records_with_ai()/detect_languages()/call_ai_json()/
combine_language_xlsx(), etc.) -- this module is only the HTTP-request-
parsing/response-shaping layer on top of it, plus a small preflight-token
cache (save_xls_preflight()/validate_xls_preflight()) that ties a Preflight
Test run to the exact Convert request that's allowed to reuse its result.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from app_state import xls_ai_lock, xls_preflight_cache, xls_preflight_lock
from customizable_transcriber.core import (
    MODELS,
    api_key,
    claude_api_key,
    humanize_provider_error,
    provider_for_model,
    validate_api_key_with_retry,
)
from http_utils import PREFLIGHT_TIMEOUT_SECONDS, extract_docx_text, parse_json_body, uploaded_docx
from profiles_store import PROJECT_DIR
from xls_conversion.ai_parser import (
    combine_language_xlsx,
    detect_languages,
    parse_records_with_ai,
    preflight_records_with_ai,
)

XLS_CONVERSION_DIR = PROJECT_DIR / "xls_conversion"


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_xls_preflight(
    result: dict[str, object],
    record_type: str,
    text: str,
    image_range: str,
    model: str,
    target_language: str,
    process_all: bool,
) -> str:
    token = secrets.token_urlsafe(24)
    with xls_preflight_lock:
        if len(xls_preflight_cache) >= 100:
            xls_preflight_cache.pop(next(iter(xls_preflight_cache)))
        xls_preflight_cache[token] = {
            "record_type": record_type,
            "source_hash": source_hash(text),
            "image_range": image_range.strip(),
            "model": model,
            "target_language": target_language.strip().lower(),
            "process_all": process_all,
            "ok": result.get("ok") is True,
        }
    return token


def validate_xls_preflight(
    token: str,
    record_type: str,
    text: str,
    image_range: str,
    model: str,
    target_language: str,
    process_all: bool,
    ignore_failure: bool,
) -> None:
    with xls_preflight_lock:
        preflight = xls_preflight_cache.get(token)
    if not preflight:
        raise RuntimeError("Run the complete preflight check before converting.")
    if (
        preflight["record_type"] != record_type
        or preflight["source_hash"] != source_hash(text)
        or preflight["image_range"] != image_range.strip()
        or preflight["model"] != model
        or preflight["target_language"] != target_language.strip().lower()
        or preflight["process_all"] != process_all
    ):
        raise RuntimeError("The source or settings changed. Run preflight again before converting.")
    if preflight["ok"] is not True and not ignore_failure:
        raise RuntimeError("Preflight found missing images or target-language material.")


class XlsConversionHandlerMixin:
    def _reserve_xls_ai_slot(self) -> bool:
        """True if this request just reserved the single shared XLS
        Conversion AI slot (see xls_ai_lock's own comment in app_state.py);
        False if Parse/Preflight/Detect Languages is already running
        elsewhere, in which case a clear 409 has already been sent and the
        caller must return immediately without proceeding."""
        if xls_ai_lock.acquire(blocking=False):
            return True
        self.respond_json(
            {
                "error": (
                    "Another XLS Conversion request (Parse, Preflight, or Detect Languages) is "
                    "already running -- wait for it to finish before starting another."
                )
            },
            status=409,
        )
        return False

    def upload_xls_source(self) -> None:
        try:
            filename, payload = uploaded_docx(self)
            text = extract_docx_text(payload)
            self.respond_json(
                {
                    "filename": filename,
                    "text": text,
                    "characters": len(text),
                }
            )
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def parse_xls_source(self) -> None:
        if not self._reserve_xls_ai_slot():
            return
        model = ""  # only meaningful once parsed below; humanize_provider_error() is
        # a no-op passthrough for any exception raised before then, so "" is never shown.
        try:
            payload = parse_json_body(self)
            model = str(payload.get("model", "") or "")
            if model not in MODELS:
                raise RuntimeError("Select a model before converting.")
            api_key_value = str(payload.get("gemini_api_key", "") or "").strip()
            if not api_key_value:
                raise RuntimeError("Paste a Gemini API key before converting.")
            record_type = str(payload.get("record_type", "") or "")
            text = str(payload.get("text", "") or "")
            image_range = str(payload.get("image_range", "") or "")
            target_language = str(payload.get("target_language", "") or "")
            target_role = str(payload.get("target_role", "") or "")
            process_all = payload.get("process_all") is True
            validate_xls_preflight(
                token=str(payload.get("preflight_token", "") or ""),
                record_type=record_type,
                text=text,
                image_range=image_range,
                model=model,
                target_language=target_language,
                process_all=process_all,
                ignore_failure=payload.get("ignore_preflight") is True,
            )
            validate_api_key_with_retry(PROJECT_DIR, model, api_key_value, timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS)
            result = parse_records_with_ai(
                record_type=record_type,
                text=text,
                image_range=image_range,
                image_overrides=str(payload.get("image_overrides", "") or ""),
                api_key=api_key_value,
                model=model,
                target_language=target_language,
                target_role=target_role,
                process_all=process_all,
            )
            self.respond_json(result)
        except Exception as exc:
            self.respond_json({"error": humanize_provider_error(exc, model)}, status=400)
        finally:
            xls_ai_lock.release()

    def preflight_xls_source(self) -> None:
        if not self._reserve_xls_ai_slot():
            return
        model = ""  # see the matching comment in parse_xls_source() above
        try:
            payload = parse_json_body(self)
            model = str(payload.get("model", "") or "")
            if model not in MODELS:
                raise RuntimeError("Select a model before running preflight.")
            api_key_value = str(payload.get("gemini_api_key", "") or "").strip()
            if not api_key_value:
                raise RuntimeError("Paste a Gemini API key before running preflight.")
            record_type = str(payload.get("record_type", "") or "")
            text = str(payload.get("text", "") or "")
            image_range = str(payload.get("image_range", "") or "")
            target_language = str(payload.get("target_language", "") or "")
            target_role = str(payload.get("target_role", "") or "")
            process_all = payload.get("process_all") is True
            filename = str(payload.get("filename", "") or "")
            validate_api_key_with_retry(PROJECT_DIR, model, api_key_value, timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS)
            result = preflight_records_with_ai(
                record_type=record_type,
                text=text,
                image_range=image_range,
                api_key=api_key_value,
                model=model,
                target_language=target_language,
                target_role=target_role,
                process_all=process_all,
                filename=filename,
            )
            token = save_xls_preflight(result, record_type, text, image_range, model, target_language, process_all)
            result["preflight_token"] = token
            result["source_hash"] = source_hash(text)
            self.respond_json(result)
        except Exception as exc:
            self.respond_json({"error": humanize_provider_error(exc, model)}, status=400)
        finally:
            xls_ai_lock.release()

    def detect_xls_languages(self) -> None:
        if not self._reserve_xls_ai_slot():
            return
        model = ""  # see the matching comment in parse_xls_source() above
        try:
            payload = parse_json_body(self)
            model = str(payload.get("model", "") or "")
            if model not in MODELS:
                raise RuntimeError("Select a model before detecting languages.")
            api_key_value = str(payload.get("gemini_api_key", "") or "").strip()
            text = str(payload.get("text", "") or "")
            image_range = str(payload.get("image_range", "") or "")
            process_all = payload.get("process_all") is True
            validate_api_key_with_retry(PROJECT_DIR, model, api_key_value, timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS)
            # validate_api_key_with_retry() above already resolves a blank
            # api_key_value to a configured .env key internally (see
            # make_client()'s own fallback, and handlers/profiles.py's
            # critique_prompt_gap()'s identical resolution) and validates
            # THAT -- this mirrors the same resolution so the real detection
            # call below actually uses the key that just passed validation,
            # instead of re-checking the original (possibly still blank)
            # pasted value and rejecting a request that had just succeeded.
            # Without this, the documented ".env works for Detect Languages"
            # convenience (README/PRIVACY.md) silently never worked at all.
            # See docs/DESIGN.md's "Security hardening history" section.
            effective_key = api_key_value or (
                claude_api_key(PROJECT_DIR) if provider_for_model(model) == "claude" else api_key(PROJECT_DIR)
            )
            result = detect_languages(
                text=text,
                image_range=image_range,
                api_key=effective_key,
                model=model,
                process_all=process_all,
            )
            self.respond_json(result)
        except Exception as exc:
            self.respond_json({"error": humanize_provider_error(exc, model)}, status=400)
        finally:
            xls_ai_lock.release()

    def combine_xls_languages(self) -> None:
        try:
            payload = parse_json_body(self)
            record_type = str(payload.get("record_type", "") or "")
            sheets_payload = payload.get("sheets")
            if not isinstance(sheets_payload, list) or len(sheets_payload) != 2:
                raise RuntimeError("Combining a workbook requires exactly two language row sets.")
            sheets: list[tuple[str, list[dict[str, str]]]] = []
            for item in sheets_payload:
                if not isinstance(item, dict):
                    raise RuntimeError("Invalid sheet payload.")
                language = str(item.get("language", "") or "")
                rows = item.get("rows")
                if not language or not isinstance(rows, list):
                    raise RuntimeError("Each sheet needs a language and its extracted rows.")
                sheets.append((language, [row for row in rows if isinstance(row, dict)]))
            xlsx_base64 = combine_language_xlsx(record_type, sheets)
            self.respond_json({"xlsx_base64": xlsx_base64})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def serve_xls_asset(self, relative_path: str) -> None:
        relative = Path(relative_path or "index.html")
        if relative.is_absolute() or ".." in relative.parts:
            self.send_error(404)
            return

        path = (XLS_CONVERSION_DIR / relative).resolve()
        try:
            path.relative_to(XLS_CONVERSION_DIR.resolve())
        except ValueError:
            self.send_error(404)
            return

        if not path.is_file():
            self.send_error(404)
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }
        content_type = content_types.get(path.suffix.lower())
        if not content_type:
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
