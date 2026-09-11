"""HTTP handlers for profile CRUD: saving/deleting a profile from the
Transcribe page's free-text editor, and every Prompt Builder save/preflight/
import/export endpoint. Business logic (where profiles live on disk, and
every load/save/update/delete/import/export operation) lives in
profiles_store.py -- this module is the HTTP-request-parsing/response-
shaping layer on top of it, plus Prompt Builder's Preflight Test's own
AI-calling logic (critique_prompt_gap()), which has nowhere else to live
since it isn't used by anything but this feature.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import httpx

from customizable_transcription.core import (
    DEFAULT_MODEL,
    FILE_TYPE_EXTENSIONS,
    MODELS,
    api_key,
    claude_api_key,
    humanize_provider_error,
    make_client,
    provider_for_model,
    sniff_file_type,
    transcribe_image,
    validate_api_key_with_retry,
)
from xls_conversion.ai_parser import call_ai_json
from profiles_store import (
    PROJECT_DIR,
    delete_profile,
    export_profile_payload,
    import_custom_profile,
    save_custom_profile,
    update_full_profile,
    update_profile,
)
from prompt_builder_content import PROMPT_BUILDER_RECORD_TYPES
from pages.prompt_builder import prompt_builder_page
from app_state import lock, state
from http_utils import PREFLIGHT_TIMEOUT_SECONDS, parse_json_body, parse_multipart_form, parse_post_form, pasted_value
from run_support import selected_profile_id

# Every category a Preflight Test suggestion can carry, and which of Prompt
# Builder's questionnaire fields it maps onto -- see applyPreflightSuggestion()
# in prompt-builder.js, which switches on this same set client-side to decide
# where a checked suggestion actually gets written. "other" is the deliberate
# escape hatch for anything real but unstructured (a phrasing convention, a
# formula tweak) -- it has no safe auto-apply target, so it renders read-only,
# with no checkbox, in the UI. Keep these two lists in sync.
PREFLIGHT_SUGGESTION_CATEGORIES = {
    "abbreviation",
    "lexicon_surname",
    "lexicon_given_name",
    "scribal_quirk",
    "relative_date_term",
    "relationship_term",
    "role_vocab",
    "other",
}


def critique_prompt_gap(
    model: str,
    full_prompt: str,
    example_entry: str,
    raw_output: str,
    record_type: str,
    api_key_override: str | None = None,
) -> list[dict[str, str]]:
    """Prompt Builder's Preflight Test: compare what the current prompt actually
    produced from one uploaded image against the user's own hand-transcribed
    Example Entry, and suggest concrete, specific gaps in the prompt's
    reference material (abbreviation key, lexicon, formulas, etc.) that likely
    explain any difference. Deliberately does not compare against a source
    image directly -- it critiques the prompt's completeness, not the AI's
    transcription accuracy on this one run, and it never edits the profile
    itself; each suggestion is classified into one of
    PREFLIGHT_SUGGESTION_CATEGORIES so the UI can offer a checkbox that adds
    it to the right questionnaire field, but nothing here writes to the
    profile -- the user decides what to accept, client-side.
    """
    key = (api_key_override or "").strip() or (
        claude_api_key(PROJECT_DIR) if provider_for_model(model) == "claude" else api_key(PROJECT_DIR)
    )
    system_prompt = (
        "You are helping a non-expert user improve a transcription prompt for archival "
        f"{record_type or 'record'} images, used to instruct an AI model that reads images of "
        "handwritten or typed source documents.\n\n"
        "You will be given three things: (1) the full system prompt currently in use, including "
        "its reference material (abbreviation key, name lexicon, formulas, vocabulary lists, "
        "etc.); (2) a known-100%-accurate example entry the user transcribed by hand from one of "
        "their own source images; (3) the AI's actual output when the current prompt was run "
        "against that same image.\n\n"
        "IMPORTANT: the source image may contain several entries (a real register page or civil "
        "act often has more than one record on it), so the AI's actual output may cover multiple "
        "entries while the known-correct example covers only ONE of them. Before comparing, first "
        "identify which single entry in the AI's output corresponds to the example -- match it by "
        "name, date, or other distinctive content. Compare ONLY that one entry against the example. "
        "Completely ignore every other entry in the output: never flag anything about content that "
        "has no counterpart in the example, even if it looks like an error, since you have no "
        "ground truth for those other entries.\n\n"
        "Compare the matched entry to the known-correct example. Identify concrete gaps in the "
        "PROMPT -- not just errors in this one run -- that likely caused any difference. Only flag "
        "real, specific differences. Do not invent generic advice, and do not comment on anything "
        "that already matches. If the two texts are effectively equivalent in content and "
        "structure, return an empty array.\n\n"
        "Classify every suggestion into EXACTLY ONE of these categories, and return the fields "
        "listed for that category (omit fields not listed):\n"
        '- "abbreviation": the example uses a written abbreviation not in the prompt\'s '
        'abbreviation key. Fields: "written" (exactly as it appears), "expansion" (the '
        'unabbreviated word/phrase), "meaning" (a short gloss), "note".\n'
        '- "lexicon_surname": a surname appears in the example that is not in the prompt\'s '
        'Surnames lexicon. Fields: "value" (the surname alone), "note".\n'
        '- "lexicon_given_name": a given name appears in the example that is not in the prompt\'s '
        'Given names lexicon. Fields: "value" (the given name alone), "note".\n'
        '- "scribal_quirk": a paleographic habit (a letterform, a mark) visible in the source that '
        'the prompt\'s scribal-quirks list does not cover. Fields: "value" (short description), '
        '"note".\n'
        '- "relative_date_term": a relative-date word/phrase (e.g. an "the same day" idiom) the '
        'example uses that the prompt\'s relative-date vocabulary does not list. Fields: "value", '
        '"note".\n'
        '- "relationship_term": a family/role relationship word the example uses that the prompt\'s '
        'relationship-terms list does not cover. Fields: "value", "note".\n'
        '- "role_vocab": a register-specific word for an entry role (e.g. how it names a witness or '
        'sponsor) that the prompt\'s role-clause vocabulary does not list. Fields: "value", "note".\n'
        '- "other": a real gap that does not fit any category above (a formula/structure mismatch, '
        "a phrasing convention, anything free-text). Fields: \"note\" only -- this category cannot "
        "be auto-applied, so explain it clearly enough for the user to act on by hand.\n\n"
        'Every suggestion object must include "category" set to one of the strings above, plus '
        'that category\'s fields. "note" is always a short, specific, human-readable explanation of '
        "the gap and why it matters -- never generic advice.\n\n"
        "Return ONLY a JSON array of these suggestion objects. No prose outside the JSON array."
    )
    user_message = (
        f"KNOWN-CORRECT EXAMPLE ENTRY (hand-transcribed by the user):\n{example_entry}\n\n"
        f"ACTUAL AI OUTPUT FROM THE UPLOADED IMAGE, USING THE CURRENT PROMPT:\n{raw_output}\n\n"
        f"CURRENT FULL PROMPT (reference material the AI had access to):\n{full_prompt}"
    )
    result = call_ai_json(key, model, system_prompt, user_message)
    if not isinstance(result, list):
        return []

    suggestions: list[dict[str, str]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip()
        if category not in PREFLIGHT_SUGGESTION_CATEGORIES:
            continue
        note = str(item.get("note") or "").strip()
        if category == "abbreviation":
            written = str(item.get("written") or "").strip()
            expansion = str(item.get("expansion") or "").strip()
            meaning = str(item.get("meaning") or "").strip()
            if not written and not expansion:
                continue  # nothing usable to offer
            suggestions.append(
                {
                    "category": category,
                    "written": written,
                    "expansion": expansion,
                    "meaning": meaning,
                    "note": note or f"Abbreviation \"{written}\" isn't in your abbreviation key.",
                }
            )
        elif category == "other":
            if not note:
                continue
            suggestions.append({"category": category, "note": note})
        else:
            value = str(item.get("value") or "").strip()
            if not value:
                continue
            suggestions.append({"category": category, "value": value, "note": note or value})
    return suggestions


class ProfilesHandlerMixin:
    def save_profile(self) -> None:
        try:
            form = parse_post_form(self)
            new_profile_name = pasted_value(form, "new_profile_name")
            profile_id = "" if new_profile_name else selected_profile_id(form)
            role_context = pasted_value(form, "role_context")
            reference_context = pasted_value(form, "reference_context")
            output_format = pasted_value(form, "output_format")
            if new_profile_name:
                profile = save_custom_profile(
                    new_profile_name,
                    role_context,
                    reference_context,
                    output_format,
                    replace_existing=form.getfirst("duplicate_profile_action", "") == "replace",
                )
                message = f"Saved new profile: {profile['label']}"
            else:
                profile = update_profile(
                    profile_id,
                    role_context,
                    reference_context,
                    output_format,
                )
                message = f"Updated profile: {profile['label']}"
            with lock:
                state["summary"] = message
                state["log"] = [message]
                state["download"] = ""
                state["profile_id"] = profile["id"]
                state["new_profile_name"] = ""
                state["role_context"] = profile.get("role_context", "")
                state["reference_context"] = profile.get("reference_context", "")
                state["output_format"] = profile.get("output_format", "")
        except Exception as exc:
            with lock:
                state["summary"] = f"Fatal error: {exc}"
                state["log"] = [f"Fatal error: {exc}"]
                state["download"] = ""
        # POST/Redirect/GET -- see the comment on /run's final
        # self.redirect_transcribe() call for why this matters.
        self.redirect_transcribe()

    def preflight_test_prompt_builder(self) -> None:
        tmp_path: Path | None = None
        model = ""  # see the matching comment in handlers/xls_conversion.py's parse_xls_source()
        try:
            files, fields = parse_multipart_form(self)

            image_entry = files.get("image")
            if not image_entry or not image_entry[1]:
                raise RuntimeError("Choose a file to upload before running the preflight test.")
            _filename, image_bytes = image_entry
            # Detected from the file's own leading bytes, not its filename --
            # see sniff_file_type() in core.py. A renamed/mislabeled upload is
            # still handled correctly (or cleanly rejected) instead of being
            # sent to the AI provider tagged with whatever MIME type its
            # extension happened to imply.
            detected_type = sniff_file_type(image_bytes)
            if detected_type is None:
                raise RuntimeError("The preflight file must be a JPEG, PNG, or PDF.")
            suffix = next(iter(FILE_TYPE_EXTENSIONS[detected_type]))

            example_entry = fields.get("example_entry", "").strip()
            if not example_entry:
                raise RuntimeError("Add an Example entry above before running the preflight test.")

            full_prompt = fields.get("full_prompt", "").strip()
            if not full_prompt:
                raise RuntimeError("Fill in the questionnaire before running the preflight test.")

            record_type = fields.get("record_type", "").strip()
            model = fields.get("model", "").strip() or DEFAULT_MODEL
            if model not in MODELS:
                raise RuntimeError("Select a valid model for the preflight test.")
            api_key_override = fields.get("api_key", "").strip() or None

            # Cheap (max_tokens=4) auth check before the real, much more
            # expensive test below (a full image plus the whole system
            # prompt, at MEDIUM thinking) -- a bad/revoked key fails in
            # under a second here instead of only surfacing after that
            # costlier call has already run. Same humanize_provider_error()
            # path handles the exception either way, so this doesn't need
            # its own except block.
            validate_api_key_with_retry(
                PROJECT_DIR, model, api_key_override, timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS
            )

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = Path(tmp.name)

            client = make_client(PROJECT_DIR, model, api_key_override, timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS)
            raw_output = transcribe_image(
                client=client,
                image_path=tmp_path,
                system_prompt=full_prompt,
                model=model,
                # Uncapped "high" reasoning on a full image plus a long system
                # prompt is appropriate for a real batch run (see
                # make_client()'s comment) but not for a single foreground
                # preflight check with no progress log -- MEDIUM keeps real
                # reasoning capacity without the unbounded default's latency.
                max_thinking_level="MEDIUM",
            )

            suggestions = critique_prompt_gap(
                model=model,
                full_prompt=full_prompt,
                example_entry=example_entry,
                raw_output=raw_output,
                record_type=record_type,
                api_key_override=api_key_override,
            )

            self.respond_json({"raw_output": raw_output, "suggestions": suggestions})
        except httpx.TimeoutException:
            self.respond_json(
                {
                    "error": (
                        f"The AI provider did not respond within {PREFLIGHT_TIMEOUT_SECONDS} seconds. "
                        "Try again, or try a different model."
                    )
                },
                status=400,
            )
        except Exception as exc:
            self.respond_json({"error": humanize_provider_error(exc, model)}, status=400)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def save_prompt_builder_draft(self) -> None:
        """JSON-in/JSON-out sibling of save_prompt_builder_profile(), used only by
        Preflight Test's auto-save-before-run step. A real save from the Save
        buttons still goes through save_prompt_builder_profile() (full page
        submit); this exists so "Run Preflight Test" can checkpoint the current
        in-progress questionnaire to disk via fetch, without navigating away
        from the page or losing the preflight results panel. Reuses the exact
        same save_custom_profile()/update_full_profile() calls, so a draft
        saved this way is a completely ordinary profile -- loadable, editable,
        and indistinguishable from one saved the normal way.
        """
        try:
            payload = parse_json_body(self)
            role_context = str(payload.get("role_context", "") or "")
            reference_context = str(payload.get("reference_context", "") or "")
            output_format = str(payload.get("output_format", "") or "")
            native_language = str(payload.get("native_language", "") or "")
            translation_languages = [
                value.strip()
                for value in str(payload.get("translation_languages", "") or "").split(",")
                if value.strip()
            ]
            record_type = str(payload.get("record_type", "") or "")
            edit_profile_id = str(payload.get("edit_profile_id", "") or "").strip()
            name = str(payload.get("name", "") or "").strip()
            pb_answers = payload.get("pb_answers")
            if not isinstance(pb_answers, dict):
                pb_answers = None

            if edit_profile_id:
                profile = update_full_profile(
                    edit_profile_id,
                    name or edit_profile_id,
                    role_context,
                    reference_context,
                    output_format,
                    native_language=native_language,
                    translation_languages=translation_languages,
                    record_type=record_type,
                    pb_answers=pb_answers,
                )
            else:
                if not name:
                    type_label = PROMPT_BUILDER_RECORD_TYPES.get(record_type, {}).get("label", "Record")
                    name = f"{type_label} draft {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                profile = save_custom_profile(
                    name,
                    role_context,
                    reference_context,
                    output_format,
                    replace_existing=False,
                    native_language=native_language,
                    translation_languages=translation_languages,
                    record_type=record_type,
                    pb_answers=pb_answers,
                )
            self.respond_json({"id": profile["id"], "label": profile["label"]})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def export_prompt_builder_profile(self, query: dict[str, str]) -> None:
        try:
            profile_id = query.get("profile_id", "")
            if not profile_id:
                raise RuntimeError("Select a profile to export.")
            filename, body = export_profile_payload(profile_id)
        except Exception as exc:
            self.send_error(400, str(exc))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def import_prompt_builder_profile(self) -> None:
        try:
            files, _fields = parse_multipart_form(self)
            file_entry = files.get("file")
            if not file_entry or not file_entry[1]:
                raise RuntimeError("Choose a profile file to import.")
            _filename, file_bytes = file_entry
            file_text = file_bytes.decode("utf-8", errors="replace")
            profile = import_custom_profile(file_text)
            self.respond_json({
                "id": profile["id"],
                "label": profile["label"],
                "has_pb_answers": bool(profile.get("pb_answers")),
            })
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def save_prompt_builder_profile(self) -> None:
        role_context = ""
        reference_context = ""
        output_format = ""
        new_profile_name = ""
        edit_profile_id = ""
        save_mode = "new"
        pb_answers: dict | None = None
        try:
            form = parse_post_form(self)
            new_profile_name = pasted_value(form, "new_profile_name")
            role_context = pasted_value(form, "role_context")
            reference_context = pasted_value(form, "reference_context")
            output_format = pasted_value(form, "output_format")
            native_language = pasted_value(form, "native_language")
            translation_languages = [
                value.strip() for value in pasted_value(form, "translation_languages").split(",") if value.strip()
            ]
            record_type = pasted_value(form, "record_type")
            edit_profile_id = pasted_value(form, "edit_profile_id")
            save_mode = form.getfirst("save_mode", "new") or "new"

            pb_answers_raw = pasted_value(form, "pb_answers_json")
            if pb_answers_raw:
                try:
                    parsed = json.loads(pb_answers_raw)
                    pb_answers = parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    pb_answers = None  # don't fail the whole save over a malformed snapshot

            if save_mode == "update" and edit_profile_id:
                profile = update_full_profile(
                    edit_profile_id,
                    new_profile_name,
                    role_context,
                    reference_context,
                    output_format,
                    native_language=native_language,
                    translation_languages=translation_languages,
                    record_type=record_type,
                    pb_answers=pb_answers,
                )
                message = (
                    f'Updated profile "{profile["label"]}". Reload the Transcribe or Test Mode '
                    "tab to see the change there."
                )
            else:
                profile = save_custom_profile(
                    new_profile_name,
                    role_context,
                    reference_context,
                    output_format,
                    replace_existing=False,
                    native_language=native_language,
                    translation_languages=translation_languages,
                    record_type=record_type,
                    pb_answers=pb_answers,
                )
                message = (
                    f'Saved profile "{profile["label"]}". Reload the Transcribe or Test Mode '
                    "tab to see it in the profile list there."
                )
            self.respond(
                prompt_builder_page(
                    new_profile_name="",
                    message=message,
                    message_kind="success",
                )
            )
        except Exception as exc:
            self.respond(
                prompt_builder_page(
                    new_profile_name=new_profile_name,
                    message=f"Could not save: {exc}",
                    message_kind="error",
                    restore_answers=pb_answers,
                    restore_edit_id=edit_profile_id if save_mode == "update" else "",
                    restore_edit_label=new_profile_name,
                )
            )

    def delete_profile(self) -> None:
        with lock:
            already_running = state["running"]
        if already_running:
            # redirect_transcribe() doesn't acquire `lock`, so it's safe to
            # call after releasing it above regardless -- see the
            # POST/Redirect/GET comment on /run's final redirect_transcribe()
            # call for why every response in this file's POST handlers now
            # redirects instead of rendering page()/test_mode_page() directly.
            self.redirect_transcribe()
            return
        try:
            form = parse_post_form(self)
            profile_id = selected_profile_id(form)
            profile = delete_profile(profile_id)
            message = f"Deleted profile: {profile.get('label', profile_id)}"
            with lock:
                state["summary"] = message
                state["log"] = [message]
                state["download"] = ""
                state["profile_id"] = ""
                state["new_profile_name"] = ""
                state["role_context"] = ""
                state["reference_context"] = ""
                state["output_format"] = ""
        except Exception as exc:
            with lock:
                state["summary"] = f"Fatal error: {exc}"
                state["log"] = [f"Fatal error: {exc}"]
                state["download"] = ""
        self.redirect_transcribe()
