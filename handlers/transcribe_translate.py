"""HTTP handlers for the Transcribe page's "Translate completed transcript"
section: a preflight of an uploaded corrected DOCX (read locally, plus one
tiny request to check the API key), starting the translation run, and
downloading its report. The work itself lives in
transcript_translation.py. A translation run uses the same run slot, Progress
Console, Stop button and Download Document link as a transcription run, so
the two can never run at once.
"""

from __future__ import annotations


from app_state import lock, output_file, state, stop_event
from customizable_transcriber.core import (
    MODELS,
    humanize_provider_error,
    ensure_key_matches_model,
    key_provider_mismatch,
    validate_api_key_with_retry,
)
from http_utils import PREFLIGHT_TIMEOUT_SECONDS, parse_multipart_form
from profiles_store import PROJECT_DIR
from transcript_translation import (
    TranslationOptions,
    build_plan,
    build_translation_prompt,
    docx_text,
    preflight_summary,
    start_translation_job,
)


def _translation_request(handler) -> tuple[str, str, str, list[str], str, str, TranslationOptions]:
    """(text, filename, profile_id, languages, model, api_key, options) from
    the multipart form. Raises RuntimeError with a user-facing message."""
    files, fields = parse_multipart_form(handler)
    filename, payload = files.get("source_file", ("", b""))
    if not payload:
        raise RuntimeError("Choose the corrected DOCX transcript first.")
    if not filename.lower().endswith(".docx"):
        raise RuntimeError("Upload a Microsoft Word DOCX file.")
    model = fields.get("model", "")
    if model not in MODELS:
        raise RuntimeError("Choose a model.")
    languages = [lang.strip() for lang in fields.get("languages", "").split(",") if lang.strip()]
    options = TranslationOptions(
        expand_abbreviations=fields.get("expand_abbreviations", "") == "on",
        convert_names=fields.get("convert_names", "") == "on",
        honorifics=[h.strip() for h in fields.get("honorifics", "").split(",") if h.strip()],
    )
    return (
        docx_text(payload),
        filename,
        fields.get("profile_id", "").strip(),
        languages,
        model,
        fields.get("api_key", "").strip(),
        options,
    )


def api_key_problem(model: str, api_key: str) -> str:
    """"" when the key works for this model, else a message saying why not.
    A key pasted for the wrong provider is caught by its shape first, with no
    request; otherwise the provider is sent the same tiny "Reply with OK."
    request the other preflights use (validate_api_key())."""
    if not api_key:
        return "Paste your API key in the API key field above."
    mismatch = key_provider_mismatch(model, api_key)
    if mismatch:
        return mismatch
    try:
        validate_api_key_with_retry(PROJECT_DIR, model, api_key, timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS)
    except Exception as exc:
        return humanize_provider_error(exc, model)
    return ""


class TranscribeTranslateHandlerMixin:
    def preflight_translation(self) -> None:
        try:
            text, _filename, profile_id, languages, model, api_key, options = _translation_request(self)
            plan = build_plan(text, profile_id, languages, options)
            # Checked even when the document has problems, so every problem
            # shows at once.
            key_problem = api_key_problem(model, api_key)
            if key_problem:
                plan.errors.append(key_problem)
            prompt_chars = (
                len(build_translation_prompt(
                    plan.profile, plan.native_language, plan.languages, plan.options, line_structure=plan.line_structure
                ))
                if plan.languages
                else 0
            )
            summary = preflight_summary(plan, prompt_chars)
            summary["api_key_valid"] = not key_problem
            summary["model_label"] = MODELS[model]
            self.respond_json(summary)
        except Exception as exc:
            self.respond_json({"ok": False, "errors": [str(exc)]}, status=400)

    def run_translation(self) -> None:
        with lock:
            already_running = state["running"]
            if not already_running:
                state["running"] = True
                stop_event.clear()
        if already_running:
            self.respond_json({"ok": False, "errors": ["A transcription or translation is already running."]}, status=409)
            return
        try:
            text, filename, profile_id, languages, model, api_key, options = _translation_request(self)
            if not api_key:
                raise RuntimeError("Paste your API key in the API key field above.")
            # The run endpoint repeats preflight's local shape check, so a
            # request that skipped preflight can't send a wrong-provider key.
            ensure_key_matches_model(model, api_key)
            plan = build_plan(text, profile_id, languages, options)
            if plan.errors:
                raise RuntimeError(" ".join(plan.errors))
        except Exception as exc:
            with lock:
                state["running"] = False
            self.respond_json({"ok": False, "errors": [str(exc)]}, status=400)
            return

        with lock:
            # Stop pressed while this run was being set up: honour it instead
            # of clearing it here (reviews/CODEX_REVIEW_8.md M-4).
            stopped_during_setup = stop_event.is_set()
            if stopped_during_setup:
                state["running"] = False
                state["summary"] = "Stopped before the translation started."
        if stopped_during_setup:
            self.respond_json({"ok": False, "errors": ["Stopped before the translation started."]}, status=409)
            return
        with lock:
            state["log"] = []
            state["output"] = ""
            state["download"] = ""
            state["report_download"] = ""
            state["off_peak"] = False
            state["summary"] = f"Translating {filename}..."
        start_translation_job(
            text, filename, str((plan.profile or {}).get("id", "")), plan.languages, model, api_key, plan.options
        )
        self.respond_json({"ok": True})

    def download_translation_report(self) -> None:
        with lock:
            report = str(state.get("report_download", ""))
        path = output_file(report)
        if path is None:
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
