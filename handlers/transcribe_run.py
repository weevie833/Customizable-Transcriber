"""HTTP handlers for the Transcribe page's run controls: starting a batch
(/run), stopping it, resetting the UI state, and the status/download
endpoints it polls. The actual background batch (run_job()) and the
profile/model/file-type resolution it depends on live in run_support.py,
shared with handlers/test_mode_run.py -- see that module's own docstring.
"""

from __future__ import annotations

import copy
import json
import threading

from app_state import lock, output_file, reset_ui_state, state, status_payload, stop_event
from customizable_transcriber.core import ensure_key_matches_model
from http_utils import parse_post_form, pasted_value
from profiles_store import load_profile_exact, save_custom_profile, update_profile
from run_support import (
    bind_source_folder,
    destination_output_file,
    preflight_source_file_type,
    run_job,
    selected_file_type,
    selected_model,
    selected_profile_id,
    selected_zoom_pages,
)


class TranscribeRunHandlerMixin:
    def run_transcription(self) -> None:
        with lock:
            # Reserve the run slot in the SAME lock acquisition as the check
            # below. Previously this flag wasn't set True until after form
            # parsing and profile loading/saving had already run unlocked, so
            # two near-simultaneous /run requests could both pass the check,
            # both proceed, and race to write the same output file. Every
            # early-return error path below now clears this back to False,
            # since a job was never actually started on that path.
            already_running = state["running"]
            if not already_running:
                state["running"] = True
                stop_event.clear()
        if already_running:
            # redirect_transcribe() (303 See Other) does not acquire `lock`,
            # so it's safe to call after releasing it above regardless --
            # but it also matters here for a second reason: see the
            # POST/Redirect/GET comment on the final self.redirect_transcribe()
            # call below, which every response in this handler now follows.
            self.redirect_transcribe()
            return

        try:
            form = parse_post_form(self)
            model = selected_model(form)
            api_key_value = pasted_value(form, "gemini_api_key")
            if not api_key_value:
                raise RuntimeError("Paste an API key before running transcription.")
            # Before the run slot is used: a key for the wrong provider is
            # refused here, as Test Mode and Translate already do
            # (GEMINI_REVIEW_9 I-2).
            ensure_key_matches_model(model, api_key_value)
            selected_profile_id(form)
            preflight_source_file_type(bind_source_folder(form), selected_file_type(form))
        except Exception as exc:
            with lock:
                state["running"] = False
                state["summary"] = f"Fatal error: {exc}"
                state["log"] = [f"Fatal error: {exc}"]
                state["download"] = ""
            self.redirect_transcribe()
            return

        order = form.getfirst("order", "oldest")
        file_type = selected_file_type(form)
        profile_id = selected_profile_id(form)
        profile_action = form.getfirst("profile_action", "use") or "use"
        new_profile_name = pasted_value(form, "new_profile_name")
        role_context = pasted_value(form, "role_context")
        reference_context = pasted_value(form, "reference_context")
        output_format = pasted_value(form, "output_format")
        try:
            if profile_action == "create" or new_profile_name:
                profile = save_custom_profile(
                    new_profile_name,
                    role_context,
                    reference_context,
                    output_format,
                    replace_existing=form.getfirst("duplicate_profile_action", "") == "replace",
                )
                profile_id = profile["id"]
                new_profile_name = ""
                form.setfirst("profile_id", profile_id)
                form.setfirst("new_profile_name", "")
            elif profile_action == "update":
                profile = update_profile(
                    profile_id,
                    role_context,
                    reference_context,
                    output_format,
                )
            else:
                profile = load_profile_exact(profile_id)
                role_context = profile.get("role_context", "")
                reference_context = profile.get("reference_context", "")
                output_format = profile.get("output_format", "")
            form.setfirst("profile_id", profile_id)
            form.setfirst("profile_action", "use")
            form.setfirst("new_profile_name", "")
        except Exception as exc:
            with lock:
                state["running"] = False
                state["summary"] = f"Fatal error: {exc}"
                state["log"] = [f"Fatal error: {exc}"]
                state["download"] = ""
            self.redirect_transcribe()
            return
        output_file = destination_output_file(profile_id)
        if order not in {"newest", "oldest"}:
            order = "oldest"
        with lock:
            # Stop pressed while this run was being set up: honour it instead
            # of clearing it here (reviews/CODEX_REVIEW_8.md M-4). The flag is
            # cleared when the slot is reserved, not at launch.
            stopped_during_setup = stop_event.is_set()
            if stopped_during_setup:
                state["running"] = False
                state["summary"] = "Stopped before the run started."
        if stopped_during_setup:
            self.redirect_transcribe()
            return
        with lock:
            state["running"] = True
            state["log"] = []
            state["output"] = str(output_file)
            state["download"] = ""
            state["report_download"] = ""
            state["summary"] = f"Running {profile['label']}..."
            state["model"] = model
            state["order"] = order
            state["file_type"] = file_type
            state["zoom_pages"] = selected_zoom_pages(form)
            state["profile_id"] = profile_id
            state["new_profile_name"] = new_profile_name
            state["role_context"] = role_context
            state["reference_context"] = reference_context
            state["output_format"] = output_format

        thread = threading.Thread(target=run_job, args=(form, output_file, copy.deepcopy(profile)), daemon=True)
        thread.start()
        # POST/Redirect/GET: the job is now started and its state committed
        # above, so redirect (303 See Other) to a plain GET of the same page
        # instead of rendering page() directly in this POST response. This is
        # the actual fix for a real reported bug -- responding to a POST with
        # 200 HTML makes the browser's history entry for this navigation a
        # POST, and a reload of it (a plain Cmd+R/F5, which prompts to
        # resubmit, or a hard reload -- Cmd+Shift+R/Ctrl+Shift+R -- which was
        # observed to resubmit silently, no prompt) resends this exact POST
        # body, restarting a whole transcription batch with no user intent to
        # run anything. A 303 redirect makes the final entry in browser
        # history a GET, which any kind of reload just re-fetches harmlessly.
        # Applied to every response in this handler (not just this one) and
        # to every other POST handler in this file that was doing the same
        # direct-render-after-POST thing -- see redirect_transcribe()'s and
        # redirect_test_mode()'s other call sites.
        self.redirect_transcribe()

    def stop_job(self) -> None:
        with lock:
            if state["running"]:
                stop_event.set()
                if state["off_peak"]:
                    # No provider network call here -- batch_transcription.py's
                    # poll loop notices stop_event on its own next tick (at most
                    # POLL_INTERVAL_SECONDS away) and calls the provider's
                    # cancel-batch endpoint itself, the same cooperative-
                    # cancellation shape run_batch() already uses between images.
                    if state.get("batch_submitting"):
                        # The batch was already being sent when Stop arrived
                        # (CODEX_REVIEW_2.md M-4): it is cancelled once the
                        # provider returns its job id, through the poll loop.
                        state["summary"] = "Stop received while the batch was being sent -- it will be cancelled once the provider confirms it."
                    else:
                        state["summary"] = "Cancelling off-peak batch..."
                    state["log"].append("Off-peak cancellation requested.")
                else:
                    state["summary"] = "Stopping after the current image finishes..."
                    state["log"].append("Stop requested.")
                state["log"] = state["log"][-300:]
            else:
                state["summary"] = "No transcription is running."
        self.redirect_transcribe()

    def reset(self) -> None:
        # The idle check and the reset happen under one lock acquisition
        # inside reset_ui_state(), so a run reserved in between can't be
        # erased (reviews/CODEX_REVIEW_8.md M-4).
        reset_ui_state()
        self.redirect_transcribe()

    def status(self) -> None:
        data = json.dumps(status_payload()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def download(self) -> None:
        with lock:
            download = str(state["download"])
        path = output_file(download)
        if path is None:
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        if path.suffix.lower() == ".docx":
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            content_type = "text/markdown; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        # Same reasoning as test_download()'s own no-store header --
        # this is generated transcription content, not a stable asset, so a
        # shared/history-visible browser cache shouldn't retain it past the run.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
