"""HTTP handler for Off-Peak Mode's /run-offpeak endpoint. Deliberately a
separate file from handlers/transcribe_run.py's real-time /run handler,
rather than a mode flag on the same one -- two single-purpose handlers,
each independently reviewable, following the exact same proven reservation
pattern, rather than one handler branching between two subtly different
lock-usage shapes.

run_off_peak() below mirrors run_transcription() (handlers/transcribe_run.py)
line for line through the reservation and profile-resolution steps -- including
its inline (not resolve_profile_for_run()) profile save/update/load handling,
since that's what the real /run handler actually does, and Off-Peak submits
the exact same <form> with the exact same profile_action/role_context/
reference_context/output_format fields (e.g. an in-place profile edit
followed immediately by "Confirm and Run Off-Peak" must be saved exactly
like clicking "Confirm and Run Now" would). It diverges only at the point
where a real-time run would spawn run_job() -- this spawns
batch_transcription.py's run_off_peak_job() instead, and commits a few
extra Off-Peak-specific state fields. See batch_transcription.py's own
module docstring for the rest of the design.
"""

from __future__ import annotations

import threading

from app_state import load_source_folder, lock, state, stop_event
from batch_transcription import run_off_peak_job
from customizable_transcription.core import provider_for_model
from http_utils import parse_post_form, pasted_value
from profiles_store import PROJECT_DIR, load_profile, save_custom_profile, update_profile
from run_support import (
    build_system_prompt,
    destination_output_file,
    extensions_for_file_type,
    preflight_source_file_type,
    selected_file_type,
    selected_model,
    selected_profile_id,
    selected_zoom_pages,
)


class TranscribeOffPeakHandlerMixin:
    def run_off_peak(self) -> None:
        with lock:
            # Identical reserve-inside-one-lock-acquisition pattern to
            # run_transcription() -- see that function's own comment on the
            # TOCTOU race this closes. v1 has no run-stacking, so this
            # occupies the exact same state["running"] slot a real-time run
            # does; a real-time run already in progress (or another
            # off-peak submission) is rejected the same way a second /run
            # is today.
            already_running = state["running"]
            if not already_running:
                state["running"] = True
        if already_running:
            self.redirect_transcribe()
            return

        try:
            form = parse_post_form(self)
            model = selected_model(form)
            api_key_value = pasted_value(form, "gemini_api_key")
            if not api_key_value:
                raise RuntimeError("Paste an API key before running transcription.")
            selected_profile_id(form)
            preflight_source_file_type(load_source_folder(), selected_file_type(form))
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
            elif profile_action == "update":
                profile = update_profile(profile_id, role_context, reference_context, output_format)
            else:
                profile = load_profile(profile_id)
        except Exception as exc:
            with lock:
                state["running"] = False
                state["summary"] = f"Fatal error: {exc}"
                state["log"] = [f"Fatal error: {exc}"]
                state["download"] = ""
            self.redirect_transcribe()
            return

        system_prompt = build_system_prompt(tool="generic", profile=profile)
        if order not in {"newest", "oldest"}:
            order = "oldest"
        docx_file = destination_output_file(profile_id)
        markdown_file = docx_file.with_suffix(".md")
        image_folder = load_source_folder()
        api_key_override = pasted_value(form, "gemini_api_key") or None

        with lock:
            stop_event.clear()
            state["running"] = True
            state["off_peak"] = True
            state["batch_provider"] = ""
            state["batch_job_id"] = ""
            state["batch_counts"] = {}
            state["log"] = []
            state["output"] = str(docx_file)
            state["download"] = ""
            state["summary"] = f"Submitting off-peak batch using {profile['label']}..."
            state["model"] = model
            state["order"] = order
            state["file_type"] = file_type
            state["zoom_pages"] = selected_zoom_pages(form)
            state["profile_id"] = profile_id
            state["new_profile_name"] = ""
            state["role_context"] = role_context
            state["reference_context"] = reference_context
            state["output_format"] = output_format

        thread = threading.Thread(
            target=run_off_peak_job,
            kwargs={
                "project_dir": PROJECT_DIR,
                "image_folder": image_folder,
                "extensions": extensions_for_file_type(file_type),
                "model": model,
                "provider": provider_for_model(model),
                "system_prompt": system_prompt,
                "api_key_override": api_key_override,
                "markdown_file": markdown_file,
                "docx_file": docx_file,
                "profile": profile,
                # See CODEX_REVIEW.md finding M-1: the confirmation UI promises
                # this order, but without threading it through, the batch was
                # always submitted (and therefore output) oldest-to-newest.
                "reverse_order": order != "oldest",
                "zoom_pages": selected_zoom_pages(form),
            },
            daemon=True,
        )
        thread.start()
        # POST/Redirect/GET -- see run_transcription()'s identical comment.
        self.redirect_transcribe()
