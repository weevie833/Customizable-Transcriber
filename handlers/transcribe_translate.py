"""HTTP handlers for the Transcribe page's "Translate completed transcript"
section: a free preflight of an uploaded corrected DOCX, starting the
translation run, and downloading its report. The work itself lives in
transcript_translation.py. A translation run uses the same run slot, Progress
Console, Stop button and Download Document link as a transcription run, so
the two can never run at once.
"""

from __future__ import annotations

from pathlib import Path

from app_state import lock, state, stop_event
from customizable_transcriber.core import MODELS
from http_utils import parse_multipart_form
from transcript_translation import (
    build_plan,
    build_translation_prompt,
    docx_text,
    preflight_summary,
    start_translation_job,
)


def _translation_request(handler) -> tuple[str, str, str, list[str], str, str]:
    """(text, filename, profile_id, languages, model, api_key) from the
    multipart form. Raises RuntimeError with a user-facing message."""
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
    return (
        docx_text(payload),
        filename,
        fields.get("profile_id", "").strip(),
        languages,
        model,
        fields.get("api_key", "").strip(),
    )


class TranscribeTranslateHandlerMixin:
    def preflight_translation(self) -> None:
        try:
            text, _filename, profile_id, languages, _model, _key = _translation_request(self)
            plan = build_plan(text, profile_id, languages)
            prompt_chars = (
                len(build_translation_prompt(plan.profile, plan.native_language, plan.languages))
                if plan.profile and plan.languages
                else 0
            )
            self.respond_json(preflight_summary(plan, prompt_chars))
        except Exception as exc:
            self.respond_json({"ok": False, "errors": [str(exc)]}, status=400)

    def run_translation(self) -> None:
        with lock:
            already_running = state["running"]
            if not already_running:
                state["running"] = True
        if already_running:
            self.respond_json({"ok": False, "errors": ["A transcription or translation is already running."]}, status=409)
            return
        try:
            text, filename, profile_id, languages, model, api_key = _translation_request(self)
            if not api_key:
                raise RuntimeError("Paste your API key in the API key field above.")
            plan = build_plan(text, profile_id, languages)
            if plan.errors:
                raise RuntimeError(" ".join(plan.errors))
        except Exception as exc:
            with lock:
                state["running"] = False
            self.respond_json({"ok": False, "errors": [str(exc)]}, status=400)
            return

        with lock:
            stop_event.clear()
            state["log"] = []
            state["output"] = ""
            state["download"] = ""
            state["report_download"] = ""
            state["off_peak"] = False
            state["summary"] = f"Translating {filename}..."
        start_translation_job(text, filename, plan.profile["id"], plan.languages, model, api_key)
        self.respond_json({"ok": True})

    def download_translation_report(self) -> None:
        with lock:
            report = str(state.get("report_download", ""))
        path = Path(report) if report else None
        if path is None or not path.exists():
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
