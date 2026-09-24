"""HTTP handlers for Test Mode's run controls (queueing batches, starting a
run, stopping/resetting, status/download) and its transcript-comparison
feature (compare_test()/compare_report()). The actual background batch
(run_test_job()) and the profile/model/file-type/batch resolution it
depends on live in run_support.py, shared with
handlers/transcribe_run.py -- see that module's own docstring.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app_state import (
    USER_OUTPUTS_DIR,
    load_source_folder,
    new_test_run_state,
    reset_test_ui_state,
    test_lock,
    test_state,
    test_status_payload,
    test_stop_event,
)
from customizable_transcription.core import key_looks_like_claude, provider_for_model
from http_utils import (
    extract_docx_text,
    parse_json_body,
    parse_multipart_form,
    parse_post_form,
    pasted_value,
    uploaded_docx_field,
)
from profiles_store import delete_profile
from run_support import (
    new_batch_id,
    output_stem,
    preflight_source_file_type,
    required_providers,
    resolve_profile_for_run,
    resolve_run_batches,
    run_test_job,
    selected_file_type,
    selected_model_pair,
    selected_profile_id,
    selected_zoom_pair,
    test_destination_output_file,
)
from test_mode.comparison import score_transcription
from test_mode.report_docx import build_compare_report_docx


class TestModeRunHandlerMixin:
    def add_to_queue(self) -> None:
        with test_lock:
            already_running = test_state["running"]
        if already_running:
            # redirect_test_mode() doesn't acquire test_lock, so it's safe
            # to call after releasing it above regardless -- see the
            # POST/Redirect/GET comment on /run's final redirect_transcribe()
            # call for why every POST handler in this file redirects instead
            # of rendering page()/test_mode_page() directly.
            self.redirect_test_mode()
            return
        try:
            form = parse_post_form(self)
            model_a, model_b = selected_model_pair(form)
            zoom_a, zoom_b = selected_zoom_pair(form)
            label = pasted_value(form, "batch_label")
            with test_lock:
                ordinal = len(test_state["queue"]) + 1
                test_state["queue"].append(
                    {
                        "batch_id": new_batch_id(),
                        "label": label or f"Batch {ordinal}",
                        "model_a": model_a,
                        "model_b": model_b,
                        "zoom_a": zoom_a,
                        "zoom_b": zoom_b,
                    }
                )
                test_state["model_a"] = model_a
                test_state["model_b"] = model_b
                test_state["zoom_a"] = zoom_a
                test_state["zoom_b"] = zoom_b
        except Exception as exc:
            with test_lock:
                test_state["summary"] = f"Fatal error: {exc}"
        self.redirect_test_mode()

    def remove_from_queue(self) -> None:
        with test_lock:
            already_running = test_state["running"]
        if already_running:
            # redirect_test_mode() doesn't acquire test_lock, so it's safe
            # to call after releasing it above regardless -- see the
            # POST/Redirect/GET comment on /run's final redirect_transcribe()
            # call for why every POST handler in this file redirects instead
            # of rendering page()/test_mode_page() directly.
            self.redirect_test_mode()
            return
        try:
            form = parse_post_form(self)
            batch_id = form.getfirst("batch_id", "") or ""
            with test_lock:
                test_state["queue"] = [
                    batch for batch in test_state["queue"] if batch["batch_id"] != batch_id
                ]
        except Exception as exc:
            with test_lock:
                test_state["summary"] = f"Fatal error: {exc}"
        self.redirect_test_mode()

    def run_test(self) -> None:
        with test_lock:
            # Reserve the run slot in the SAME lock acquisition as the check
            # below -- see the matching comment on handlers/transcribe_run.py's
            # run_transcription() for why: two near-simultaneous requests
            # could otherwise both pass the check, both proceed through form
            # parsing/profile loading unlocked, and race to rebuild the same
            # test_state/runs_init. Every early-return error path below
            # clears this back to False.
            already_running = test_state["running"]
            if not already_running:
                test_state["running"] = True
        if already_running:
            # redirect_test_mode() doesn't acquire test_lock, so it's safe
            # to call after releasing it above regardless -- see the
            # POST/Redirect/GET comment on /run's final redirect_transcribe()
            # call for why every POST handler in this file redirects instead
            # of rendering page()/test_mode_page() directly.
            self.redirect_test_mode()
            return

        try:
            form = parse_post_form(self)
            api_key_gemini = pasted_value(form, "api_key_gemini")
            api_key_claude = pasted_value(form, "api_key_claude")
            file_type = selected_file_type(form)
            preflight_source_file_type(load_source_folder(), file_type)
            batches = resolve_run_batches(form)
            # Keys are entered per provider, not per A/B slot -- see
            # required_providers()'s own comment. Only the provider(s) at
            # least one queued batch actually needs must have a key filled
            # in; a queue that never uses Claude, say, doesn't need the
            # Claude field touched at all.
            needed = required_providers(batches)
            if "gemini" in needed and not api_key_gemini:
                raise RuntimeError(
                    "Paste a Gemini API key -- at least one queued run uses a Gemini model."
                )
            if "claude" in needed and not api_key_claude:
                raise RuntimeError(
                    "Paste a Claude API key -- at least one queued run uses a Claude model."
                )
            if api_key_gemini and key_looks_like_claude(api_key_gemini):
                raise RuntimeError(
                    "The Gemini API key field doesn't look like a Gemini key -- it looks like a Claude key instead."
                )
            if api_key_claude and not key_looks_like_claude(api_key_claude):
                raise RuntimeError("The Claude API key doesn't look like a Claude key.")
            profile = resolve_profile_for_run(form)
            profile_id = profile["id"]
        except Exception as exc:
            with test_lock:
                test_state["running"] = False
                test_state["summary"] = f"Fatal error: {exc}"
                test_state["log"] = [f"Fatal error: {exc}"]
            self.redirect_test_mode()
            return

        order = form.getfirst("order", "oldest")
        if order not in {"newest", "oldest"}:
            order = "oldest"

        stem = output_stem()
        run_specs: list[tuple[str, str, str, str, Path, Path]] = []
        runs_init: dict[str, dict[str, str | bool]] = {}
        for batch in batches:
            for slot, model in (("a", batch["model_a"]), ("b", batch["model_b"])):
                api_key_value = api_key_claude if provider_for_model(model) == "claude" else api_key_gemini
                run_id = f"{batch['batch_id']}-{slot}"
                zoom_pages = bool(batch.get(f"zoom_{slot}"))
                # The label names Page zoom so the comparison report can tell
                # "same model, with and without zoom" apart.
                label = f"{batch['label']} · Model {slot.upper()}" + (" (Page zoom)" if zoom_pages else "")
                output_file = test_destination_output_file(profile_id, run_id, model, stem)
                markdown_file = USER_OUTPUTS_DIR / f"{output_file.stem}.md"
                run_specs.append((run_id, label, model, api_key_value, markdown_file, output_file))
                run_state = new_test_run_state()
                run_state.update(
                    {
                        "batch_label": batch["label"],
                        "label": label,
                        "model": model,
                        "output": str(output_file),
                        "zoom_pages": zoom_pages,
                    }
                )
                runs_init[run_id] = run_state

        with test_lock:
            test_stop_event.clear()
            test_state["running"] = True
            test_state["current_run_id"] = ""
            test_state["log"] = []
            test_state["summary"] = f"Running {len(batches)} batch(es), {len(run_specs)} run(s) total..."
            test_state["order"] = order
            test_state["file_type"] = file_type
            test_state["profile_id"] = profile_id
            test_state["queue"] = []
            test_state["runs"] = runs_init

        thread = threading.Thread(target=run_test_job, args=(form, run_specs), daemon=True)
        thread.start()
        # POST/Redirect/GET -- see the comment on handlers/transcribe_run.py's
        # run_transcription()'s final self.redirect_transcribe() call for why
        # every response in this handler (and every other POST handler in
        # this app) redirects instead of rendering test_mode_page()/page()
        # directly: without it, a reload of this response's history entry --
        # including a hard reload (Cmd+Shift+R/Ctrl+Shift+R), observed to
        # resubmit silently with no confirmation prompt -- resends this exact
        # POST and starts a whole second batch of test runs with no user
        # intent to do so.
        self.redirect_test_mode()

    def delete_test_profile(self) -> None:
        with test_lock:
            already_running = test_state["running"]
        if already_running:
            # redirect_test_mode() doesn't acquire test_lock, so it's safe
            # to call after releasing it above regardless -- see the
            # POST/Redirect/GET comment on /run's final redirect_transcribe()
            # call for why every POST handler in this file redirects instead
            # of rendering page()/test_mode_page() directly.
            self.redirect_test_mode()
            return
        try:
            form = parse_post_form(self)
            profile_id = selected_profile_id(form)
            profile = delete_profile(profile_id)
            message = f"Deleted profile: {profile.get('label', profile_id)}"
            with test_lock:
                test_state["summary"] = message
                test_state["log"] = [message]
                test_state["profile_id"] = ""
        except Exception as exc:
            with test_lock:
                test_state["summary"] = f"Fatal error: {exc}"
                test_state["log"] = [f"Fatal error: {exc}"]
        self.redirect_test_mode()

    def stop_test_job(self) -> None:
        with test_lock:
            if test_state["running"]:
                test_stop_event.set()
                test_state["summary"] = "Stopping after the current image finishes..."
                test_state["log"].append("Stop requested.")
                test_state["log"] = test_state["log"][-300:]
            else:
                test_state["summary"] = "No test run is running."
        self.redirect_test_mode()

    def reset_test(self) -> None:
        with test_lock:
            if test_state["running"]:
                self.redirect_test_mode()
                return
        test_stop_event.clear()
        reset_test_ui_state()
        self.redirect_test_mode()

    def test_status(self) -> None:
        data = json.dumps(test_status_payload()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def test_download(self, run_id: str) -> None:
        with test_lock:
            download = str(test_state["runs"].get(run_id, {}).get("download", ""))
        if not download:
            self.send_error(404)
            return
        path = Path(download)
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def compare_test(self) -> None:
        try:
            files, fields = parse_multipart_form(self)
            corrected_text = extract_docx_text(uploaded_docx_field(files, "corrected_file"))

            contestants: list[tuple[str, str, str]] = []  # (label, model, text)

            try:
                selected_run_ids = json.loads(fields.get("selected_run_ids", "[]"))
            except json.JSONDecodeError:
                selected_run_ids = []
            if not isinstance(selected_run_ids, list):
                selected_run_ids = []

            with test_lock:
                runs_snapshot = {run_id: dict(run) for run_id, run in test_state["runs"].items()}

            for run_id in selected_run_ids:
                run = runs_snapshot.get(str(run_id))
                if not run:
                    continue
                markdown_path = Path(run.get("markdown", ""))
                if not markdown_path.exists():
                    raise RuntimeError(f"{run.get('label') or run_id}'s transcription output was not found.")
                text = markdown_path.read_text(encoding="utf-8")
                contestants.append((run.get("label") or str(run_id), run.get("model", ""), text))

            extra_indexes = sorted(
                (name.removeprefix("extra_model_file_") for name in files if name.startswith("extra_model_file_")),
                key=lambda value: int(value) if value.isdigit() else value,
            )
            for index in extra_indexes:
                payload = uploaded_docx_field(files, f"extra_model_file_{index}")
                label = fields.get(f"extra_model_label_{index}", "").strip() or f"Uploaded model {index}"
                text = extract_docx_text(payload)
                contestants.append((label, "", text))

            if not contestants:
                raise RuntimeError("Select at least one completed run or upload a model DOCX to compare.")

            results = []
            for label, model, text in contestants:
                score = score_transcription(corrected_text, text)
                results.append({"label": label, "model": model, **score})

            results.sort(key=lambda entry: entry["cer"])
            for rank, entry in enumerate(results, start=1):
                entry["rank"] = rank

            self.respond_json({"results": results})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def compare_report(self) -> None:
        try:
            payload = parse_json_body(self)
            results = payload.get("results")
            if not isinstance(results, list) or not results:
                raise RuntimeError("Run a comparison before downloading a report.")
            corrected_label = str(payload.get("corrected_label") or "")
            data = build_compare_report_docx(results, corrected_label)
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            self.send_header("Content-Disposition", 'attachment; filename="transcription-comparison-report.docx"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)
