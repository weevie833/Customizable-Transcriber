from __future__ import annotations

import html
import hashlib
import http.cookies
import io
import json
import os
import platform
import re
import secrets
import subprocess
import tempfile
import threading
import urllib.parse
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree

import httpx

from customizable_transcription.core import (
    DEFAULT_MODEL,
    FILE_TYPE_EXTENSIONS,
    MODELS,
    TranscriptionConfig,
    api_key,
    claude_api_key,
    count_failures,
    count_source_files_by_type,
    default_output_file,
    extensions_for_file_type,
    key_matches_provider,
    make_client,
    provider_for_model,
    run_batch,
    sniff_file_type,
    transcribe_image,
    validate_api_key,
)
from xls_conversion.ai_parser import (
    call_ai_json,
    combine_language_xlsx,
    detect_languages,
    parse_records_with_ai,
    preflight_records_with_ai,
)
from test_mode.comparison import score_transcription
from test_mode.report_docx import build_compare_report_docx
from docx_package import content_types_xml, root_rels_xml, strip_xml_illegal_chars
from index_compare.reader import NeedsMapping, resolve_index_file, suggest_mapping
from index_compare.report_xlsx import build_index_compare_report
from index_compare.scoring import compare_indexes
from xls_conversion.ai_parser import RECORD_TYPES
from prompt_builder_content import (
    PROMPT_BUILDER_COMMON_ABBREVIATIONS,
    PROMPT_BUILDER_CORE_RULES,
    PROMPT_BUILDER_RECORD_TYPES,
    PROMPT_BUILDER_RELATIONSHIP_TERMS,
    PROMPT_BUILDER_RELATIVE_DATE_TERMS,
    PROMPT_BUILDER_SCRIBAL_QUIRKS,
    PROMPT_BUILDER_SECTION_HELP,
)
from profiles_store import (
    PROFILES_DIR,
    PROJECT_DIR,
    USER_DATA_DIR,
    USER_PROFILES_DIR,
    delete_profile,
    ensure_profiles_dir,
    export_profile_payload,
    find_profile_path,
    import_custom_profile,
    load_custom_profiles,
    load_profile,
    profile_id_from_name,
    profile_options_html,
    profiles_for_browser,
    profiles_with_display_labels,
    safe_filename,
    save_custom_profile,
    update_full_profile,
    update_profile,
)
from app_state import (
    APP_SETTINGS_FILE,
    USER_OUTPUTS_DIR,
    add_log,
    add_test_log,
    clear_source_folder,
    load_source_folder,
    lock,
    new_test_run_state,
    reset_test_ui_state,
    reset_ui_state,
    save_source_folder,
    state,
    status_payload,
    stop_event,
    test_lock,
    test_state,
    test_status_payload,
    test_stop_event,
    xls_preflight_cache,
    xls_preflight_lock,
)
from pages.privacy import privacy_page
from pages.home import home_page
from pages.transcribe import page
from pages.test_mode import test_mode_page
from pages.prompt_builder import prompt_builder_page


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
        return None
    morsel = jar.get(CSRF_COOKIE_NAME)
    return morsel.value if morsel else None
# Per-call cap for Prompt Builder's Preflight Test only (see make_client()'s
# timeout_seconds param and critique_prompt_gap()) -- matches
# xls_conversion/ai_parser.py's own AI_REQUEST_TIMEOUT_SECONDS. Two AI calls
# happen per preflight run (transcribe, then critique), so a slow provider can
# still take up to ~2x this before the request as a whole gives up; each call
# fails cleanly with a clear error at this bound rather than hanging
# indefinitely, which is what a genai.Client with no http_options timeout
# does. The real Transcribe page's batch run deliberately keeps no such cap --
# see make_client()'s own comment.
PREFLIGHT_TIMEOUT_SECONDS = 90
MAX_FORM_BYTES = 5_000_000
MAX_DOCX_BYTES = 50_000_000
MAX_JSON_BYTES = 15_000_000
# Caps the *decompressed* size of word/document.xml specifically -- MAX_DOCX_BYTES
# above only bounds the compressed upload, and a small, deliberately-repetitive
# zip entry can expand far past that (verified: a ~0.5MB crafted file decompressed
# to 1GB+ in memory with no cap in place). 20MB is generous for a transcription's
# worth of plain text/XML markup -- a real Word document.xml this large would
# already be an unusually long document.
MAX_DOCX_XML_BYTES = 20_000_000
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

# PROJECT_DIR/PROFILES_DIR/USER_DATA_DIR/USER_PROFILES_DIR (imported above
# from profiles_store) are this app's own repo-root and profile directories.
# USER_OUTPUTS_DIR/APP_SETTINGS_FILE, the in-memory run state
# (state/test_state and their locks/events), and the source-folder settings
# functions all live in app_state.py now -- see its module docstring for why
# (pages/*.py needs them too, and importing them from app.py would be
# circular since app.py imports the page-render functions from pages/*.py).
XLS_CONVERSION_DIR = PROJECT_DIR / "xls_conversion"
STATIC_DIR = PROJECT_DIR / "static"
FILE_TYPE_LABELS = {
    "jpeg": "JPEG (.jpg, .jpeg)",
    "png": "PNG (.png)",
    "pdf": "PDF (.pdf)",
}


def output_stem() -> str:
    return default_output_file(PROJECT_DIR).stem


class FormData:
    def __init__(self, values: Mapping[str, list[str]]) -> None:
        self.values = values

    def getfirst(self, name: str, default: str | None = None) -> str | None:
        values = self.values.get(name)
        if not values:
            return default
        return values[0]

    def setfirst(self, name: str, value: str) -> None:
        self.values[name] = [value]


def parse_post_form(handler: BaseHTTPRequestHandler) -> FormData:
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise RuntimeError("Unsupported form submission type.")

    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Invalid form submission length.") from exc

    if content_length < 0 or content_length > MAX_FORM_BYTES:
        raise RuntimeError("Invalid form submission length.")

    body = handler.rfile.read(content_length).decode("utf-8")
    return FormData(urllib.parse.parse_qs(body, keep_blank_values=True))


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise RuntimeError("Unsupported request type.")
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Invalid request length.") from exc
    if content_length <= 0 or content_length > MAX_JSON_BYTES:
        raise RuntimeError("Invalid request length.")
    try:
        payload = json.loads(handler.rfile.read(content_length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The conversion request is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("The conversion request must be a JSON object.")
    return payload


def uploaded_docx(handler: BaseHTTPRequestHandler) -> tuple[str, bytes]:
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise RuntimeError("Choose a DOCX file to upload.")

    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Invalid upload length.") from exc

    if content_length <= 0 or content_length > MAX_DOCX_BYTES:
        raise RuntimeError("The DOCX upload must be smaller than 50 MB.")

    body = handler.rfile.read(content_length)
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\n"
        b"MIME-Version: 1.0\r\n\r\n" + body
    )
    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") != "source_file":
            continue
        filename = Path(part.get_filename() or "").name
        if not filename.lower().endswith(".docx"):
            raise RuntimeError("Upload a Microsoft Word DOCX file.")
        payload = part.get_payload(decode=True) or b""
        if not payload:
            raise RuntimeError("The uploaded DOCX file is empty.")
        return filename, payload

    raise RuntimeError("Choose a DOCX file to upload.")


def parse_multipart_form(
    handler: BaseHTTPRequestHandler,
) -> tuple[dict[str, tuple[str, bytes]], dict[str, str]]:
    """Split one multipart/form-data POST into file parts and plain text fields.

    Returns (files, fields): files maps field name to (filename, payload);
    fields maps field name to its decoded text value. A field is treated as a
    file if the part declares a filename, matching how <input type="file">
    and plain <input>/hidden fields differ in the multipart body.
    """
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise RuntimeError("Choose files to upload.")

    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Invalid upload length.") from exc

    if content_length <= 0 or content_length > MAX_DOCX_BYTES:
        raise RuntimeError("The upload must be smaller than 50 MB.")

    body = handler.rfile.read(content_length)
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\n"
        b"MIME-Version: 1.0\r\n\r\n" + body
    )
    files: dict[str, tuple[str, bytes]] = {}
    fields: dict[str, str] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        if filename is not None:
            payload = part.get_payload(decode=True) or b""
            files[name] = (Path(filename).name, payload)
        else:
            payload = part.get_payload(decode=True) or b""
            fields[name] = payload.decode("utf-8", errors="replace")
    return files, fields


def uploaded_docx_field(
    files: dict[str, tuple[str, bytes]],
    field_name: str,
    required: bool = True,
) -> bytes:
    """Pull one named .docx file out of a parse_multipart_form() files dict."""
    entry = files.get(field_name)
    if not entry or not entry[1]:
        if required:
            raise RuntimeError(f"Upload a file for {field_name.replace('_', ' ')} before comparing.")
        return b""
    filename, payload = entry
    if not filename.lower().endswith(".docx"):
        raise RuntimeError(f"{field_name.replace('_', ' ').title()} must be a .docx file.")
    return payload


def extract_docx_text(payload: bytes) -> str:
    # Two ingestion-safety checks, verified against real crafted input before
    # this was added: (1) ZipInfo.file_size is the archive's own *declared*
    # uncompressed size, checked before ever calling .read() -- a ~0.5MB
    # zip with one deliberately-repetitive entry decompressed to 1GB+ with no
    # cap in place, so this must happen before decompression, not after.
    # (2) a real Word document.xml never has a DOCTYPE -- it's pure content,
    # no DTD -- so rejecting one outright (rather than trying to selectively
    # allow "safe" entities) closes the XML entity-expansion ("billion
    # laughs") path with no false positives on legitimate files. A 605-byte
    # crafted payload with 6 nested entity levels expanded to 300,000 chars
    # in 10ms with no guard in place; ElementTree.fromstring() does not
    # protect against this on its own.
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise RuntimeError("The DOCX document's content is too large to process.")
            document_xml = archive.read(info)
    except (KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError("The uploaded file is not a readable DOCX document.") from exc

    # Anywhere in the document, not just at the very start: an anchored
    # "^\s*(<?xml...?>)?<!DOCTYPE" check is bypassable by putting anything
    # else first -- a comment or processing instruction (`<!--x--><!DOCTYPE
    # ...>`) slides straight past it and reaches ElementTree.fromstring()
    # below with the DOCTYPE (and any entities it declares) intact,
    # reopening the exact billion-laughs path the check above exists to
    # close. A real Word document.xml never contains either token under any
    # circumstances, so a plain substring search has no false positives.
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", document_xml, re.IGNORECASE):
        raise RuntimeError("The uploaded file is not a readable DOCX document.")

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise RuntimeError("The DOCX document text could not be read.") from exc

    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraphs: list[str] = []
    for paragraph_node in root.iter(f"{{{namespace}}}p"):
        parts: list[str] = []
        for node in paragraph_node.iter():
            if node.tag == f"{{{namespace}}}t":
                parts.append(node.text or "")
            elif node.tag == f"{{{namespace}}}tab":
                parts.append("\t")
            elif node.tag in {f"{{{namespace}}}br", f"{{{namespace}}}cr"}:
                parts.append("\n")
        paragraphs.append("".join(parts).rstrip())

    text = "\n".join(paragraphs).strip()
    if not text:
        raise RuntimeError("No transcription text was found in the DOCX document.")
    return text


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


def destination_output_file(profile_id: str) -> Path:
    return USER_OUTPUTS_DIR / f"{safe_filename(profile_id)}-{output_stem()}.docx"


def test_destination_output_file(profile_id: str, run_id: str, model: str, stem: str) -> Path:
    return (
        USER_OUTPUTS_DIR
        / f"{safe_filename(profile_id)}-{stem}-{safe_filename(run_id)}-{safe_filename(model)}.docx"
    )


def selected_model(form: FormData) -> str:
    model = form.getfirst("model", DEFAULT_MODEL) or DEFAULT_MODEL
    if model not in MODELS:
        raise RuntimeError("Select a model before running transcription.")
    return model


def selected_model_pair(form: FormData) -> tuple[str, str]:
    model_a = form.getfirst("model_a", DEFAULT_MODEL) or DEFAULT_MODEL
    model_b = form.getfirst("model_b", DEFAULT_MODEL) or DEFAULT_MODEL
    if model_a not in MODELS or model_b not in MODELS:
        raise RuntimeError("Select a model for both Model A and Model B before running.")
    if model_a == model_b:
        raise RuntimeError("Model A and Model B must be different models.")
    return model_a, model_b


def new_batch_id() -> str:
    return f"batch-{secrets.token_hex(4)}"


def resolve_run_batches(form: FormData) -> list[dict[str, str]]:
    """The queued batches to run, or a single implicit batch from the current
    Model A/Model B selects if the user never used "Add to Batch"."""
    with test_lock:
        queue = [dict(batch) for batch in test_state["queue"]]
    if queue:
        return queue
    model_a, model_b = selected_model_pair(form)
    return [
        {
            "batch_id": new_batch_id(),
            "label": "Batch 1",
            "model_a": model_a,
            "model_b": model_b,
        }
    ]


def selected_file_type(form: FormData) -> str:
    file_type = form.getfirst("file_type", "jpeg") or "jpeg"
    if file_type not in FILE_TYPE_EXTENSIONS:
        raise RuntimeError("Select JPEG, PNG, or PDF as the source file type.")
    return file_type


def file_type_display(file_type: str) -> str:
    return FILE_TYPE_LABELS.get(file_type, file_type.upper())


def preflight_source_file_type(source_folder: Path | None, file_type: str) -> int:
    if source_folder is None:
        raise RuntimeError("Choose a source folder before running (use the Browse… button above).")
    counts = count_source_files_by_type(source_folder)
    selected_count = counts.get(file_type, 0)
    if selected_count:
        return selected_count
    available = [
        f"{file_type_display(kind)}: {count}"
        for kind, count in counts.items()
        if count
    ]
    if available:
        detail = " Available source files: " + ", ".join(available) + "."
    else:
        detail = " No JPEG, PNG, or PDF source files were found."
    raise RuntimeError(f"No {file_type_display(file_type)} files were found in the source folder.{detail}")


def pasted_value(form: FormData, name: str) -> str:
    return (form.getfirst(name, "") or "").strip()


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


def _pick_source_folder_macos() -> str | None:
    """Native Finder "choose folder" dialog via AppleScript. Runs as an
    independent OS process (not bound to the calling Python thread's GUI
    affinity), which matters because ThreadingHTTPServer handles each request
    on its own thread — a GUI toolkit living inside this process (e.g.
    tkinter) would need to run on the main thread on macOS; shelling out
    sidesteps that entirely, and the same reasoning applies to the Windows
    and Linux variants below."""
    script = 'POSIX path of (choose folder with prompt "Select the source folder for transcription images")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Couldn't open the folder picker: {exc}") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if "User canceled" in stderr or "-128" in stderr:
            return None
        raise RuntimeError(stderr or "Couldn't open the folder picker.")
    chosen = result.stdout.strip()
    return chosen or None


def _pick_source_folder_windows() -> str | None:
    """Native folder-browse dialog via .NET's FolderBrowserDialog, run
    through PowerShell as a separate process. `-STA` (single-threaded
    apartment) is required for WinForms dialogs to display correctly."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$dialog.Description = 'Select the source folder for transcription images';"
        "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.SelectedPath }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Couldn't open the folder picker: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip() or "Couldn't open the folder picker.")
    # Empty stdout means the user closed the dialog without clicking OK — not an error.
    chosen = result.stdout.strip()
    return chosen or None


def _pick_source_folder_linux() -> str | None:
    """Native folder dialog via zenity (GNOME/GTK) if it's installed; there is
    no single cross-desktop-environment API to fall back to on Linux the way
    osascript/PowerShell provide one on Mac/Windows, so an unavailable zenity
    surfaces as a clear error pointing at the manual-path fallback rather than
    a silent failure."""
    try:
        result = subprocess.run(
            [
                "zenity",
                "--file-selection",
                "--directory",
                "--title=Select the source folder for transcription images",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No folder-picker dialog is available (zenity is not installed). "
            "Type the folder path directly in the field below instead."
        ) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Couldn't open the folder picker: {exc}") from exc
    if result.returncode != 0:
        return None  # zenity exits 1 on Cancel/Escape
    chosen = result.stdout.strip()
    return chosen or None


def pick_source_folder_dialog() -> str | None:
    """Show the platform's native folder-choose dialog and return the chosen
    absolute path, or None if the user canceled. Raises RuntimeError on any
    other failure. Dispatches by platform.system() so this works the same way
    (a real native dialog, not a browser file input — a browser can't hand
    back an absolute filesystem path for the backend to read from disk) on
    macOS, Windows, and Linux."""
    system = platform.system()
    if system == "Darwin":
        return _pick_source_folder_macos()
    if system == "Windows":
        return _pick_source_folder_windows()
    if system == "Linux":
        return _pick_source_folder_linux()
    raise RuntimeError(
        f"No folder-picker dialog is available on this platform ({system}). "
        "Type the folder path directly in the field below instead."
    )


def open_folder_in_file_manager(path: Path) -> None:
    """Reveals `path` in the native file manager (Finder/Explorer/whatever
    the Linux desktop's default is) via the same per-OS subprocess dispatch
    pattern as pick_source_folder_dialog() above, and for the same reason:
    generated outputs now live in a per-user data directory outside the app
    folder (see USER_OUTPUTS_DIR) rather than somewhere a user would already
    have open, and on macOS that directory sits under the normally-hidden
    ~/Library -- printing the raw path in the UI (which this app also still
    does) isn't enough for a non-technical user to actually get there."""
    system = platform.system()
    path.mkdir(parents=True, exist_ok=True)
    try:
        if system == "Darwin":
            result = subprocess.run(["open", str(path)], capture_output=True, text=True, timeout=15)
        elif system == "Windows":
            # explorer.exe routinely exits 1 even when it opens the window
            # successfully -- a documented quirk, not a failure signal -- so
            # a non-zero returncode is not treated as an error below, unlike
            # the other two branches.
            result = subprocess.run(["explorer", str(path)], capture_output=True, text=True, timeout=15)
            return
        elif system == "Linux":
            result = subprocess.run(["xdg-open", str(path)], capture_output=True, text=True, timeout=15)
        else:
            raise RuntimeError(f"Can't open a file manager window on this platform ({system}).")
    except FileNotFoundError as exc:
        raise RuntimeError(f"No file manager command was found to open {path}.") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Couldn't open the outputs folder: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip() or f"Couldn't open {path}.")


def selected_profile_id(form: FormData) -> str:
    profile_id = form.getfirst("profile_id", "") or ""
    if not profile_id:
        raise RuntimeError("Select a prompt profile before running transcription.")
    if find_profile_path(profile_id) is not None:
        return profile_id
    raise RuntimeError("Select a valid prompt profile before running transcription.")


def resolve_profile_for_run(form: FormData) -> dict[str, str]:
    profile_id = selected_profile_id(form)
    profile_action = form.getfirst("profile_action", "use") or "use"
    new_profile_name = pasted_value(form, "new_profile_name")
    role_context = pasted_value(form, "role_context")
    reference_context = pasted_value(form, "reference_context")
    output_format = pasted_value(form, "output_format")

    if profile_action == "create" or new_profile_name:
        return save_custom_profile(
            new_profile_name,
            role_context,
            reference_context,
            output_format,
            replace_existing=form.getfirst("duplicate_profile_action", "") == "replace",
        )

    if profile_action == "update":
        return update_profile(
            profile_id,
            role_context,
            reference_context,
            output_format,
        )

    return load_profile(profile_id)
def default_custom_output_format(tool: str) -> str:
    if tool == "generic":
        return (
            "Italian Transcription:\n"
            "[Continuous, source-faithful transcription.]\n\n"
            "English Translation:\n"
            "[Faithful English translation.]"
        )
    return (
        "Italian Transcription:\n"
        "[Continuous, source-faithful transcription for each record or unit.]\n\n"
        "English Translation:\n"
        "[Faithful English translation.]\n\n"
        "Extracted Fields:\n"
        "[Use only fields visible in the source or supplied by the user output format.]"
    )


def neutral_system_scaffold(tool: str, role_context: str, output_format: str) -> str:
    role = role_context or (
        "You are an expert paleographer and historian specializing in handwritten archival "
        "records. Use only the user-supplied local reference material and what is visible in "
        "the source image; do not rely on assumptions from any unrelated locality."
    )
    format_text = output_format or default_custom_output_format(tool)

    return (
        "# ROLE AND LOCAL CONTEXT\n"
        + role
        + "\n\n"
        "# CORE TRANSCRIPTION RULES\n"
        "- Output only what is present in the source image.\n"
        "- Do not include a filename or START OF RECORD header; the app adds that automatically.\n"
        "- Preserve original spellings, archaic forms, non-standard forms, capitalization, and punctuation when visible.\n"
        "- Preserve abbreviations exactly as written in the transcription.\n"
        "- Expand clear abbreviations only in the English translation.\n"
        "- Do not preserve source line breaks; use continuous paragraphs unless the output format requires separate fields.\n"
        "- A line break may fall in the middle of a single word (commonly marked with a hyphen) or between the separate words of one name or phrase (for example a given name on one line of a margin note and the surname on the next, with no hyphen at all). Either way, rejoin the pieces with a plain space (or no space, for a mid-word split) and nothing else. Never output a hyphen, slash, pipe, or any other mark in place of the line break; the break is a page-layout artifact, not punctuation the scribe wrote.\n"
        "- If a marginal heading, margin note, or similar per-entry annotation contains a standalone number anywhere alongside a name, move that number to the very front of that block's text, formatted as \"Entry N - \" directly before the name -- no matter where the number physically appears in the source, and regardless of whether you are certain it is the register's own entry number. If its meaning is genuinely unclear, still reposition it this way and note the uncertainty separately (for example in Notes) rather than leaving the number in its original position. Never leave a number trailing after a name or sitting elsewhere in that block's text: a downstream step reads that block as a name field, and any number left attached to it becomes part of the name. This is the only place that number belongs -- never repeat it in the page/act locator line above, which identifies the page or act only.\n"
        "- Do not summarize, modernize, normalize, or invent missing words.\n"
        "- Use brackets for uncertain readings, for example [Rovella?] or [illegible].\n"
        "- If part of the page is unreadable, mark only that portion as [illegible].\n"
        "- If the output format defines a block that transcribes one specific location on the page separately "
        "from the entry body (for example, a marginal heading), that block must contain only what is written "
        "in that location. Never copy, infer, or supplement it with content from another block, another "
        "location on the page, or the entry formula -- even when the same information genuinely appears "
        "elsewhere in the entry. If two such blocks disagree, transcribe each exactly as it appears in its own "
        "location and flag the disagreement; do not resolve it by editing either block.\n\n"
        "# OUTPUT FORMAT\n"
        + format_text
    )


def build_system_prompt(tool: str, profile: dict[str, str]) -> str:
    role_context = profile.get("role_context", "")
    reference_context = profile.get("reference_context", "")
    output_format = profile.get("output_format", "")
    if not any((role_context, reference_context, output_format)):
        raise RuntimeError("The selected custom profile has no role, reference, or output format content.")

    sections = [neutral_system_scaffold(tool, role_context, output_format)]
    if reference_context:
        sections.append(
            "# USER-SUPPLIED GROUND TRUTH AND REFERENCE MATERIAL\n"
            "Use the following material as the primary local knowledge base for this run. "
            ""
            "It may include JSON dictionaries, names, places, formulas, abbreviations, sample "
            "transcriptions/translations, or other ground-truth notes. Do not invent content "
            "from this reference; use it only to resolve or constrain readings visible in the source image.\n\n"
            "```text\n"
            + reference_context
            + "\n```"
        )
    return "\n\n".join(sections)





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
    without touching this function's page shell (nav/CSS/footer). Read in and
    substituted via plain string replace, not an f-string, since the CSS below
    is full of literal `{`/`}` that would otherwise all need doubling."""
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
  <style>
    .panel p {
      margin: 12px 0;
    }
    .gs-intro {
      margin: 0 0 18px;
      color: #5f6b76;
    }
    details.gs-section {
      background: #ffffff;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 14px;
    }
    details.gs-section summary {
      cursor: pointer;
      list-style: none;
      display: flex;
      align-items: baseline;
      gap: 10px;
      font-weight: 700;
      font-size: 17px;
    }
    details.gs-section summary::-webkit-details-marker {
      display: none;
    }
    details.gs-section summary::before {
      content: "\\25B8";
      color: #255c99;
      display: inline-block;
      transition: transform 0.12s ease;
    }
    details.gs-section[open] summary::before {
      transform: rotate(90deg);
    }
    .gs-body {
      margin-top: 14px;
    }
    .gs-body p {
      margin: 12px 0;
    }
    .gs-body ul, .gs-body ol {
      margin: 12px 0;
      padding-left: 24px;
    }
    .gs-body li {
      margin: 6px 0;
    }
    .gs-body a {
      color: #255c99;
    }
    .gs-example {
      background: #f4f5f6;
      border: 1px solid #d9d4c8;
      border-radius: 6px;
      padding: 10px 14px;
      margin: 12px 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    @media (max-width: 720px) {
      .site-header { align-items: stretch; }
    }
  </style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<main id="main-content" tabindex="-1">
  <header class="site-header">
    <div class="site-heading">
      <h1>Getting Started</h1>
      <div class="byline-row">
        <p class="byline">Created by Steve Covello, 2026</p>
        <div class="lang-toggle" role="group" aria-label="Language / Lingua">
          <button type="button" class="lang-flag" data-lang="en" aria-pressed="true" title="English" aria-label="English">🇺🇸</button>
          <button type="button" class="lang-flag" data-lang="it" aria-pressed="false" title="Italiano" aria-label="Italiano">🇮🇹</button>
        </div>
      </div>
    </div>
    <nav class="site-nav" aria-label="Primary navigation">
      <a class="nav-link nav-home" href="/" aria-label="Home" title="Home">🏠</a>
      <a class="nav-link" href="/prompt-builder">Prompt Builder</a>
      <a class="nav-link" href="/transcribe">Transcribe</a>
      <a class="nav-link" href="/xls-conversion">XLSX Conversion</a>
      <a class="nav-link" href="/test-mode">Test Mode</a>
    </nav>
  </header>

  <div data-lang-block="en">
%%GETTING_STARTED_EN%%  </div>

  <div data-lang-block="it" hidden>
%%GETTING_STARTED_IT%%  </div>

  <footer class="license">Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). Free to use, modify, and share — derivative works, including hosted versions, must stay open source under the same license. &middot; <a href="/privacy">Privacy</a> <span id="app-version"></span></footer>
</main>
</body>
</html>"""
    return page.replace("%%GETTING_STARTED_EN%%", content_en).replace("%%GETTING_STARTED_IT%%", content_it)





def paragraph(text: str) -> ElementTree.Element:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = ElementTree.Element(f"{{{ns}}}p")
    # This document ships no word/styles.xml part, so every paragraph falls
    # back to Word's own built-in default (not this app's choice) -- which
    # includes ~8pt "space after" on top of the paragraph break itself. Since
    # write_docx() already puts each source line in its own paragraph, that
    # stacked with Word's default reads as doubled spacing. Zero it explicitly
    # so a paragraph break is the only vertical space between lines.
    p_pr = ElementTree.SubElement(p, f"{{{ns}}}pPr")
    spacing = ElementTree.SubElement(p_pr, f"{{{ns}}}spacing")
    spacing.set(f"{{{ns}}}after", "0")
    r = ElementTree.SubElement(p, f"{{{ns}}}r")
    t = ElementTree.SubElement(r, f"{{{ns}}}t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    # ElementTree's own serializer escapes "<"/">"/"&" but does nothing about
    # a raw control character in .text -- it isn't well-formed XML at all no
    # matter how it's escaped, and a stray one (from OCR/AI output) produces
    # a .docx Word can't open. See docx_package.strip_xml_illegal_chars().
    t.text = strip_xml_illegal_chars(text)
    return p


def header_box_element(
    native_language: str,
    translation_languages: list[str],
    record_type: str = "",
    model: str = "",
    profile_label: str = "",
) -> ElementTree.Element:
    """A bordered, shaded box stamped at the top of the transcription DOCX,
    declaring what this document contains: record type, native language, any
    translations, and (for human comparison tracking only -- the XLSX
    Conversion parser never reads these two lines) which AI model and which
    prompt profile produced this run. Written deterministically from the
    saved profile's own fields and the run's own config -- not inferred from
    the model's output -- so it's a fact the app already knows, not a guess
    made after the fact.

    The record-type/native-language/translations lines are Prompt Builder
    profiles only for now (see CLAUDE.md) and are omitted individually when
    their value is blank -- a manual-override profile has none of them set.
    The model/profile lines have no such restriction and are shown whenever
    the caller has them, which is unconditionally for every real run; the
    whole box is only skipped when write_docx() has nothing at all to put in
    it. record_type is the same key/label pair XLS Conversion's own "Source
    material" dropdown uses (PROMPT_BUILDER_RECORD_TYPES), so that page can
    match the label back to a dropdown option without a separate lookup
    table; an unrecognized or blank key just omits the line."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    record_type_label = PROMPT_BUILDER_RECORD_TYPES.get(record_type, {}).get("label", "")
    # This box is generated once, server-side, and baked into a downloaded file --
    # there is no browser toggle to retranslate it after the fact the way i18n.js
    # retranslates the live pages, and no signal at generation time for which
    # language the transcriber prefers. So the three machine-parsed lines below
    # (Record type / Native-language transcription / Translations produced) stay
    # English-only, exactly as xls_conversion/app.js's regexes require -- but the
    # purely human-facing lines (the two instructional sentences, and the AI
    # model / prompt profile tracking lines) are bilingual, EN then IT, so an
    # Italian-speaking user gets a native-language read of this box without
    # touching anything the parser depends on.
    lines = [
        ("DO NOT EDIT OR DELETE THIS BLOCK", True),
        ("NON MODIFICARE O ELIMINARE QUESTO BLOCCO", True),
        (
            "Native language, record type, and translations (if present) are read by the "
            "XLSX Conversion tool. AI model and prompt profile are recorded here for "
            "comparison tracking only.",
            False,
        ),
        (
            "La lingua nativa, il tipo di registro e le traduzioni (se presenti) vengono lette "
            "dallo strumento di conversione XLSX. Il modello IA e il profilo prompt sono "
            "registrati qui solo a scopo di tracciamento e confronto.",
            False,
        ),
    ]
    if record_type_label:
        lines.append((f"Record type: {record_type_label}", False))
    if native_language.strip():
        translations_line = ", ".join(translation_languages) if translation_languages else "None"
        lines.append((f"Native-language transcription: {native_language}", False))
        lines.append((f"Translations produced: {translations_line}", False))
    if model.strip():
        lines.append((f"AI model: {model}", False))
        lines.append((f"Modello IA: {model}", False))
    if profile_label.strip():
        lines.append((f"Prompt profile: {profile_label}", False))
        lines.append((f"Profilo prompt: {profile_label}", False))

    tbl = ElementTree.Element(f"{{{ns}}}tbl")
    tbl_pr = ElementTree.SubElement(tbl, f"{{{ns}}}tblPr")
    tbl_w = ElementTree.SubElement(tbl_pr, f"{{{ns}}}tblW")
    tbl_w.set(f"{{{ns}}}w", "0")
    tbl_w.set(f"{{{ns}}}type", "auto")
    borders = ElementTree.SubElement(tbl_pr, f"{{{ns}}}tblBorders")
    for edge in ("top", "left", "bottom", "right"):
        border = ElementTree.SubElement(borders, f"{{{ns}}}{edge}")
        border.set(f"{{{ns}}}val", "single")
        border.set(f"{{{ns}}}sz", "12")
        border.set(f"{{{ns}}}space", "0")
        border.set(f"{{{ns}}}color", "A33A2B")
    grid = ElementTree.SubElement(tbl, f"{{{ns}}}tblGrid")
    ElementTree.SubElement(grid, f"{{{ns}}}gridCol")

    tr = ElementTree.SubElement(tbl, f"{{{ns}}}tr")
    tc = ElementTree.SubElement(tr, f"{{{ns}}}tc")
    tc_pr = ElementTree.SubElement(tc, f"{{{ns}}}tcPr")
    shd = ElementTree.SubElement(tc_pr, f"{{{ns}}}shd")
    shd.set(f"{{{ns}}}val", "clear")
    shd.set(f"{{{ns}}}fill", "FBEAE7")
    tc_margins = ElementTree.SubElement(tc_pr, f"{{{ns}}}tcMar")
    for side in ("top", "left", "bottom", "right"):
        margin = ElementTree.SubElement(tc_margins, f"{{{ns}}}{side}")
        margin.set(f"{{{ns}}}w", "150")
        margin.set(f"{{{ns}}}type", "dxa")

    for line_text, bold in lines:
        p = ElementTree.SubElement(tc, f"{{{ns}}}p")
        # Same "no styles.xml, so zero Word's implicit 8pt default explicitly"
        # fix as paragraph() above -- otherwise this box's own lines get the
        # same doubled-spacing look as the transcription body below it.
        p_pr = ElementTree.SubElement(p, f"{{{ns}}}pPr")
        spacing = ElementTree.SubElement(p_pr, f"{{{ns}}}spacing")
        spacing.set(f"{{{ns}}}after", "0")
        r = ElementTree.SubElement(p, f"{{{ns}}}r")
        if bold:
            r_pr = ElementTree.SubElement(r, f"{{{ns}}}rPr")
            ElementTree.SubElement(r_pr, f"{{{ns}}}b")
        t = ElementTree.SubElement(r, f"{{{ns}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = strip_xml_illegal_chars(line_text)
    return tbl


def document_xml(text: str, header_box: ElementTree.Element | None = None) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ElementTree.register_namespace("w", ns)
    document = ElementTree.Element(f"{{{ns}}}document")
    body = ElementTree.SubElement(document, f"{{{ns}}}body")
    if header_box is not None:
        body.append(header_box)
        body.append(paragraph(""))
    for line in text.splitlines():
        body.append(paragraph(line))
    sect_pr = ElementTree.SubElement(body, f"{{{ns}}}sectPr")
    pg_sz = ElementTree.SubElement(sect_pr, f"{{{ns}}}pgSz")
    pg_sz.set(f"{{{ns}}}w", "12240")
    pg_sz.set(f"{{{ns}}}h", "15840")
    pg_mar = ElementTree.SubElement(sect_pr, f"{{{ns}}}pgMar")
    pg_mar.set(f"{{{ns}}}top", "1440")
    pg_mar.set(f"{{{ns}}}right", "1440")
    pg_mar.set(f"{{{ns}}}bottom", "1440")
    pg_mar.set(f"{{{ns}}}left", "1440")
    return ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)


def write_docx(
    output_docx: Path,
    text: str,
    native_language: str = "",
    translation_languages: list[str] | None = None,
    record_type: str = "",
    model: str = "",
    profile_label: str = "",
) -> None:
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    header_box = (
        header_box_element(
            native_language.strip(),
            translation_languages or [],
            record_type.strip(),
            model.strip(),
            profile_label.strip(),
        )
        if native_language.strip() or model.strip() or profile_label.strip()
        else None
    )
    with zipfile.ZipFile(output_docx, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr("[Content_Types].xml", content_types_xml())
        output.writestr("_rels/.rels", root_rels_xml())
        output.writestr("word/document.xml", document_xml(text, header_box))


def run_job(form: FormData, output_file: Path) -> None:
    try:
        image_folder = load_source_folder()
        file_type = selected_file_type(form)
        markdown_file = USER_OUTPUTS_DIR / f"{output_file.stem}.md"
        delay = 2.0
        profile = resolve_profile_for_run(form)
        system_prompt = build_system_prompt(
            tool="generic",
            profile=profile,
        )
        if profile.get("kind") == "custom":
            add_log(f"Using custom prompt profile: {profile['label']}")
        else:
            add_log(f"Using prompt profile: {profile['label']}")

        source_count = preflight_source_file_type(image_folder, file_type)
        add_log(f"Found {source_count} {file_type_display(file_type)} source file(s) for this run.")

        add_log("Checking API key...")
        validate_api_key(
            PROJECT_DIR,
            selected_model(form),
            pasted_value(form, "gemini_api_key") or None,
        )
        add_log("API key validated.")

        config = TranscriptionConfig(
            image_folder=image_folder,
            output_file=markdown_file,
            prompt_file=PROFILES_DIR,
            model=selected_model(form),
            delay_seconds=delay,
            reverse_order=form.getfirst("order", "oldest") != "oldest",
            system_prompt=system_prompt,
            api_key_override=pasted_value(form, "gemini_api_key") or None,
            source_extensions=extensions_for_file_type(file_type),
        )
        results = run_batch(
            config,
            PROJECT_DIR,
            progress=add_log,
            cancel_requested=stop_event.is_set,
        )
        if markdown_file.exists():
            write_docx(
                output_file,
                markdown_file.read_text(encoding="utf-8"),
                native_language=str(profile.get("native_language", "")),
                translation_languages=list(profile.get("translation_languages") or []),
                record_type=str(profile.get("record_type", "")),
                model=config.model,
                profile_label=str(profile.get("label", "")),
            )
        else:
            add_log(f"Markdown output was not found for Word export: {markdown_file}")
        failures = count_failures(results)
        with lock:
            if stop_event.is_set():
                state["summary"] = f"Stopped after {len(results)} image(s), {failures} failure(s)."
            else:
                state["summary"] = f"Processed {len(results)} image(s), {failures} failure(s)."
            state["download"] = str(output_file) if output_file.exists() else ""
    except Exception as exc:
        add_log(f"Fatal error: {exc}")
        with lock:
            state["summary"] = f"Fatal error: {exc}"
    finally:
        with lock:
            state["running"] = False


def run_test_job(
    form: FormData,
    run_specs: list[tuple[str, str, str, str, Path, Path]],
) -> None:
    """Run every queued (batch, model) pair's full image batch, one after another.

    run_specs is (run_id, label, model, api_key, markdown_file, output_file).
    Each entry already carries the API key for its own model slot (Model A's
    key for every "-a" run, Model B's key for every "-b" run — see run_test()
    below) so a queue that mixes Gemini and Claude pairs still sends each run
    to the right provider with the right key. Each iteration is an
    independent run_batch() call: its own TranscriptionConfig, its own
    markdown/docx output files, and its own fresh client (created inside
    run_batch via make_client). Nothing from one run — its output text, its
    log, anything — is read back into another run's prompt or config, so
    every run in the queue is unaffected by whatever the others produced, no
    matter how many pairs are queued.
    """
    try:
        image_folder = load_source_folder()
        file_type = selected_file_type(form)
        profile = resolve_profile_for_run(form)
        system_prompt = build_system_prompt(tool="generic", profile=profile)
        if profile.get("kind") == "custom":
            add_test_log(f"Using custom prompt profile: {profile['label']}")
        else:
            add_test_log(f"Using prompt profile: {profile['label']}")

        source_count = preflight_source_file_type(image_folder, file_type)
        add_test_log(f"Found {source_count} {file_type_display(file_type)} source file(s) for this run.")

        reverse_order = form.getfirst("order", "oldest") != "oldest"

        for run_id, label, model, api_key_value, markdown_file, output_file in run_specs:
            if test_stop_event.is_set():
                add_test_log(f"Stopped before {label} started.")
                break

            with test_lock:
                test_state["current_run_id"] = run_id

            tag = f"[{label}: {model}]"
            add_test_log(f"{tag} Checking API key before starting image processing...")
            validate_api_key(PROJECT_DIR, model, api_key_value)
            add_test_log(f"{tag} API key validated. Starting run.")

            config = TranscriptionConfig(
                image_folder=image_folder,
                output_file=markdown_file,
                prompt_file=PROFILES_DIR,
                model=model,
                delay_seconds=2.0,
                reverse_order=reverse_order,
                system_prompt=system_prompt,
                api_key_override=api_key_value,
                source_extensions=extensions_for_file_type(file_type),
            )
            results = run_batch(
                config,
                PROJECT_DIR,
                progress=lambda message, tag=tag: add_test_log(f"{tag} {message}"),
                cancel_requested=test_stop_event.is_set,
            )
            if markdown_file.exists():
                write_docx(
                    output_file,
                    markdown_file.read_text(encoding="utf-8"),
                    native_language=str(profile.get("native_language", "")),
                    translation_languages=list(profile.get("translation_languages") or []),
                )
            else:
                add_test_log(f"{tag} Markdown output was not found for Word export: {markdown_file}")
            failures = count_failures(results)
            with test_lock:
                run_state = test_state["runs"].get(run_id)
                if run_state is not None:
                    if test_stop_event.is_set():
                        run_state["summary"] = (
                            f"Stopped after {len(results)} image(s), {failures} failure(s)."
                        )
                    else:
                        run_state["summary"] = (
                            f"Processed {len(results)} image(s), {failures} failure(s)."
                        )
                    run_state["download"] = str(output_file) if output_file.exists() else ""
                    run_state["markdown"] = str(markdown_file) if markdown_file.exists() else ""

        with test_lock:
            if test_stop_event.is_set():
                test_state["summary"] = "Stopped."
            else:
                completed = sum(1 for run in test_state["runs"].values() if run["download"])
                total = len(test_state["runs"])
                test_state["summary"] = f"{completed}/{total} run(s) complete."
    except Exception as exc:
        add_test_log(f"Fatal error: {exc}")
        with test_lock:
            test_state["summary"] = f"Fatal error: {exc}"
    finally:
        with test_lock:
            test_state["running"] = False
            test_state["current_run_id"] = ""


class Handler(BaseHTTPRequestHandler):
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
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
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

        if urllib.parse.urlparse(self.path).path == "/api/index-compare/inspect":
            self.inspect_index_file()
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

        if self.path != "/run":
            self.send_error(404)
            return

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
        if already_running:
            # page() acquires `lock` itself to read state -- must be called
            # after releasing it above, never from inside the same `with
            # lock:` block, or this deadlocks the thread handling this
            # request (threading.Lock is not reentrant). Reproduced: two
            # genuinely concurrent /run requests hung forever before this
            # fix, confirmed via tests/test_run_concurrency.py.
            self.respond(page())
            return

        try:
            form = parse_post_form(self)
            model = selected_model(form)
            api_key_value = pasted_value(form, "gemini_api_key")
            if not api_key_value:
                raise RuntimeError("Paste a Gemini API key before running transcription.")
            selected_profile_id(form)
            preflight_source_file_type(load_source_folder(), selected_file_type(form))
        except Exception as exc:
            with lock:
                state["running"] = False
                state["summary"] = f"Fatal error: {exc}"
                state["log"] = [f"Fatal error: {exc}"]
                state["download"] = ""
            self.respond(page())
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
                profile = load_profile(profile_id)
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
            self.respond(page())
            return
        output_file = destination_output_file(profile_id)
        if order not in {"newest", "oldest"}:
            order = "oldest"
        with lock:
            stop_event.clear()
            state["running"] = True
            state["log"] = []
            state["output"] = str(output_file)
            state["download"] = ""
            state["summary"] = f"Running {profile['label']}..."
            state["model"] = model
            state["order"] = order
            state["file_type"] = file_type
            state["profile_id"] = profile_id
            state["new_profile_name"] = new_profile_name
            state["role_context"] = role_context
            state["reference_context"] = reference_context
            state["output_format"] = output_format

        thread = threading.Thread(target=run_job, args=(form, output_file), daemon=True)
        thread.start()
        self.respond(page())

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
            validate_api_key(PROJECT_DIR, model, api_key_value)
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
            self.respond_json({"error": str(exc)}, status=400)

    def preflight_xls_source(self) -> None:
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
            validate_api_key(PROJECT_DIR, model, api_key_value)
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
            self.respond_json({"error": str(exc)}, status=400)

    def detect_xls_languages(self) -> None:
        try:
            payload = parse_json_body(self)
            model = str(payload.get("model", "") or "")
            if model not in MODELS:
                raise RuntimeError("Select a model before detecting languages.")
            api_key_value = str(payload.get("gemini_api_key", "") or "").strip()
            text = str(payload.get("text", "") or "")
            image_range = str(payload.get("image_range", "") or "")
            process_all = payload.get("process_all") is True
            validate_api_key(PROJECT_DIR, model, api_key_value)
            result = detect_languages(
                text=text,
                image_range=image_range,
                api_key=api_key_value,
                model=model,
                process_all=process_all,
            )
            self.respond_json(result)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

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
        self.respond(page())

    def preflight_test_prompt_builder(self) -> None:
        tmp_path: Path | None = None
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
            self.respond_json({"error": str(exc)}, status=400)
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
            # page() acquires `lock` itself -- must run after releasing it
            # above, not from inside the same `with lock:` block (deadlock,
            # threading.Lock is not reentrant).
            self.respond(page())
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
        self.respond(page())

    def stop_job(self) -> None:
        with lock:
            if state["running"]:
                stop_event.set()
                state["summary"] = "Stopping after the current image finishes..."
                state["log"].append("Stop requested.")
                state["log"] = state["log"][-300:]
            else:
                state["summary"] = "No transcription is running."
        self.respond(page())

    def reset(self) -> None:
        with lock:
            if state["running"]:
                self.redirect_transcribe()
                return
        stop_event.clear()
        reset_ui_state()
        self.redirect_transcribe()

    def add_to_queue(self) -> None:
        with test_lock:
            already_running = test_state["running"]
        if already_running:
            # test_mode_page() acquires test_lock itself -- must run after
            # releasing it above, not from inside the same `with test_lock:`
            # block (deadlock, threading.Lock is not reentrant).
            self.respond(test_mode_page())
            return
        try:
            form = parse_post_form(self)
            model_a, model_b = selected_model_pair(form)
            label = pasted_value(form, "batch_label")
            with test_lock:
                ordinal = len(test_state["queue"]) + 1
                test_state["queue"].append(
                    {
                        "batch_id": new_batch_id(),
                        "label": label or f"Batch {ordinal}",
                        "model_a": model_a,
                        "model_b": model_b,
                    }
                )
                test_state["model_a"] = model_a
                test_state["model_b"] = model_b
        except Exception as exc:
            with test_lock:
                test_state["summary"] = f"Fatal error: {exc}"
        self.respond(test_mode_page())

    def remove_from_queue(self) -> None:
        with test_lock:
            already_running = test_state["running"]
        if already_running:
            # test_mode_page() acquires test_lock itself -- must run after
            # releasing it above, not from inside the same `with test_lock:`
            # block (deadlock, threading.Lock is not reentrant).
            self.respond(test_mode_page())
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
        self.respond(test_mode_page())

    def run_test(self) -> None:
        with test_lock:
            # Reserve the run slot in the SAME lock acquisition as the check
            # below -- see the matching comment on the /run handler for why:
            # two near-simultaneous requests could otherwise both pass the
            # check, both proceed through form parsing/profile loading
            # unlocked, and race to rebuild the same test_state/runs_init.
            # Every early-return error path below clears this back to False.
            already_running = test_state["running"]
            if not already_running:
                test_state["running"] = True
        if already_running:
            # test_mode_page() acquires test_lock itself -- must be called
            # after releasing it above, never from inside the same `with
            # test_lock:` block, or this deadlocks the thread handling this
            # request (threading.Lock is not reentrant).
            self.respond(test_mode_page())
            return

        try:
            form = parse_post_form(self)
            api_key_a = pasted_value(form, "api_key_a")
            api_key_b = pasted_value(form, "api_key_b")
            if not api_key_a or not api_key_b:
                raise RuntimeError("Paste an API key for both Model A and Model B before running.")
            file_type = selected_file_type(form)
            preflight_source_file_type(load_source_folder(), file_type)
            batches = resolve_run_batches(form)
            for batch in batches:
                if not key_matches_provider(batch["model_a"], api_key_a):
                    provider = provider_for_model(batch["model_a"]).capitalize()
                    raise RuntimeError(
                        f"\"{batch['label']}\": the Model A API key doesn't look like a {provider} key."
                    )
                if not key_matches_provider(batch["model_b"], api_key_b):
                    provider = provider_for_model(batch["model_b"]).capitalize()
                    raise RuntimeError(
                        f"\"{batch['label']}\": the Model B API key doesn't look like a {provider} key."
                    )
            profile = resolve_profile_for_run(form)
            profile_id = profile["id"]
        except Exception as exc:
            with test_lock:
                test_state["running"] = False
                test_state["summary"] = f"Fatal error: {exc}"
                test_state["log"] = [f"Fatal error: {exc}"]
            self.respond(test_mode_page())
            return

        order = form.getfirst("order", "oldest")
        if order not in {"newest", "oldest"}:
            order = "oldest"

        stem = output_stem()
        run_specs: list[tuple[str, str, str, str, Path, Path]] = []
        runs_init: dict[str, dict[str, str]] = {}
        for batch in batches:
            for slot, model, api_key_value in (
                ("a", batch["model_a"], api_key_a),
                ("b", batch["model_b"], api_key_b),
            ):
                run_id = f"{batch['batch_id']}-{slot}"
                label = f"{batch['label']} · Model {slot.upper()}"
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
        self.respond(test_mode_page())

    def delete_test_profile(self) -> None:
        with test_lock:
            already_running = test_state["running"]
        if already_running:
            # test_mode_page() acquires test_lock itself -- must run after
            # releasing it above, not from inside the same `with test_lock:`
            # block (deadlock, threading.Lock is not reentrant).
            self.respond(test_mode_page())
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
        self.respond(test_mode_page())

    def stop_test_job(self) -> None:
        with test_lock:
            if test_state["running"]:
                test_stop_event.set()
                test_state["summary"] = "Stopping after the current image finishes..."
                test_state["log"].append("Stop requested.")
                test_state["log"] = test_state["log"][-300:]
            else:
                test_state["summary"] = "No test run is running."
        self.respond(test_mode_page())

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

    def _index_compare_file_bytes(
        self, files: dict[str, tuple[str, bytes]], field_name: str, *, required: bool = True
    ) -> bytes:
        """Pull one named .xlsx file out of a parse_multipart_form() files
        dict -- the Index Compare analog of uploaded_docx_field()."""
        entry = files.get(field_name)
        if not entry or not entry[1]:
            if required:
                raise RuntimeError(f"Upload a file for {field_name.replace('_', ' ')}.")
            return b""
        filename, payload = entry
        if not filename.lower().endswith(".xlsx"):
            raise RuntimeError(f"{field_name.replace('_', ' ').title()} must be an .xlsx file.")
        return payload

    def _resolve_index_file_or_record_mapping_need(
        self, file_bytes: bytes, mapping_json: str, slot: str, needs_mapping: list[dict]
    ) -> tuple | None:
        """Wraps index_compare.reader.resolve_index_file(): on success
        returns its (config, rows, sheet_name); on NeedsMapping, appends a
        {slot, worksheets} entry to `needs_mapping` and returns None instead
        of raising, so the caller can keep resolving the *other* uploaded
        files and report every file that needs attention in one response
        rather than making the user fix them one at a time."""
        try:
            mapping = json.loads(mapping_json) if mapping_json else None
            return resolve_index_file(file_bytes, mapping)
        except NeedsMapping as exc:
            needs_mapping.append(
                {
                    "slot": slot,
                    "worksheets": [
                        {"name": ws.name, "header_row1": ws.header_row1, "header_row2": ws.header_row2}
                        for ws in exc.worksheets
                    ],
                }
            )
            return None

    def inspect_index_file(self) -> None:
        """Single-file precheck, called client-side right after each file
        input is chosen (before Run Comparison) -- lets the frontend show a
        column-mapping step immediately for a file that needs one, instead
        of the user discovering it only after filling in every other field
        and clicking Run."""
        try:
            files, _fields = parse_multipart_form(self)
            file_bytes = self._index_compare_file_bytes(files, "file")
            try:
                config, rows, sheet_name = resolve_index_file(file_bytes)
                self.respond_json(
                    {
                        "auto_detected": True,
                        "record_type": config.key,
                        "sheet_name": sheet_name,
                        "row_count": len(rows),
                    }
                )
            except NeedsMapping as exc:
                self.respond_json(
                    {
                        "auto_detected": False,
                        "worksheets": [
                            {"name": ws.name, "header_row1": ws.header_row1, "header_row2": ws.header_row2}
                            for ws in exc.worksheets
                        ],
                        "record_types": [{"value": key, "label": cfg.label} for key, cfg in RECORD_TYPES.items()],
                    }
                )
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def suggest_index_mapping(self) -> None:
        """Once the frontend knows a file needs mapping and the user has
        picked which of the 6 record types it is, this returns a best-guess
        column mapping (index_compare.reader.suggest_mapping()) to pre-fill
        the mapping UI, rather than making the user start from a blank
        dropdown for every field."""
        try:
            payload = parse_json_body(self)
            record_type = str(payload.get("record_type", ""))
            config = RECORD_TYPES.get(record_type)
            if not config:
                raise RuntimeError("Select a valid record type.")
            header_row1 = payload.get("header_row1")
            header_row2 = payload.get("header_row2")
            if not isinstance(header_row1, list) or not isinstance(header_row2, list):
                raise RuntimeError("Missing this worksheet's header rows.")
            mapping = suggest_mapping(record_type, [str(v) for v in header_row1], [str(v) for v in header_row2])
            self.respond_json(
                {
                    "fields": config.fields,
                    "field_group_labels": list(config.group_headers),
                    "field_column_labels": list(config.column_headers),
                    "mapping": mapping,
                }
            )
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def analyze_index_compare(self) -> None:
        try:
            files, fields = parse_multipart_form(self)
            needs_mapping: list[dict] = []

            config = None
            ground_truth = None
            gt_entry = files.get("ground_truth_file")
            if gt_entry and gt_entry[1]:
                gt_bytes = self._index_compare_file_bytes(files, "ground_truth_file", required=False)
                resolved = self._resolve_index_file_or_record_mapping_need(
                    gt_bytes, fields.get("ground_truth_mapping", ""), "ground_truth", needs_mapping
                )
                if resolved:
                    gt_config, gt_rows, _sheet = resolved
                    gt_label = fields.get("ground_truth_label", "").strip() or "Ground truth"
                    ground_truth = (gt_label, gt_rows)
                    config = gt_config

            candidate_indexes = sorted(
                (name.removeprefix("candidate_file_") for name in files if name.startswith("candidate_file_")),
                key=lambda value: int(value) if value.isdigit() else value,
            )
            candidates: list[tuple[str, list[dict[str, str]]]] = []
            for index in candidate_indexes:
                file_bytes = self._index_compare_file_bytes(files, f"candidate_file_{index}")
                resolved = self._resolve_index_file_or_record_mapping_need(
                    file_bytes, fields.get(f"candidate_mapping_{index}", ""), f"candidate_{index}", needs_mapping
                )
                if resolved is None:
                    continue
                candidate_config, rows, _sheet = resolved
                if config is None:
                    config = candidate_config
                elif candidate_config.key != config.key:
                    raise RuntimeError(
                        f"All files must be the same record type -- expected {config.label}, but "
                        f"candidate {index} looks like {candidate_config.label}."
                    )
                label = fields.get(f"candidate_label_{index}", "").strip() or f"Candidate {index}"
                candidates.append((label, rows))

            if needs_mapping:
                self.respond_json(
                    {
                        "needs_mapping": needs_mapping,
                        "record_types": [{"value": key, "label": cfg.label} for key, cfg in RECORD_TYPES.items()],
                    }
                )
                return

            if not candidates:
                raise RuntimeError("Upload at least one candidate index to compare.")
            if config is None:
                raise RuntimeError("Could not determine a record type from the uploaded files.")

            use_ai = fields.get("use_ai") == "true"
            api_key_value = fields.get("api_key", "").strip()
            model = fields.get("model", "").strip()
            if use_ai:
                if not api_key_value or not model:
                    raise RuntimeError("Paste an API key and pick a model to use AI-assisted classification.")
                validate_api_key(PROJECT_DIR, model, api_key_value)

            result = compare_indexes(
                config, ground_truth, candidates, use_ai=use_ai, api_key=api_key_value, model=model
            )
            self.respond_json(
                {
                    "result": result,
                    "record_type": config.key,
                    "ground_truth_label": ground_truth[0] if ground_truth else "",
                }
            )
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def index_compare_report(self) -> None:
        try:
            payload = parse_json_body(self)
            result = payload.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Run a comparison before downloading a report.")
            ground_truth_label = str(payload.get("ground_truth_label") or "")
            # Optional: lets the report render real column labels ("Father's
            # Given Name") instead of internal field names -- absent this,
            # build_index_compare_report() just falls back to the raw names.
            config = RECORD_TYPES.get(str(payload.get("record_type") or ""))
            data = build_index_compare_report(result, ground_truth_label, config)
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            self.send_header("Content-Disposition", 'attachment; filename="index-comparison-report.xlsx"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def pick_source_folder(self) -> None:
        try:
            chosen = pick_source_folder_dialog()
            if chosen is None:
                self.respond_json({"canceled": True})
                return
            path = Path(chosen)
            if not path.is_dir():
                raise RuntimeError(f"{path} is not a folder.")
            save_source_folder(path)
            self.respond_json({"source_folder": str(path)})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def set_source_folder(self) -> None:
        """Manual-entry fallback for platforms/setups where the native folder
        dialog isn't available (e.g. Linux without zenity), or for a user who
        just wants to type/paste a path directly."""
        try:
            payload = parse_json_body(self)
            raw = str(payload.get("path") or "").strip()
            if not raw:
                raise RuntimeError("Enter a folder path.")
            path = Path(raw).expanduser()
            if not path.is_dir():
                raise RuntimeError(f"{path} is not a folder, or doesn't exist on this machine.")
            save_source_folder(path)
            self.respond_json({"source_folder": str(path)})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def open_outputs_folder(self) -> None:
        try:
            open_folder_in_file_manager(USER_OUTPUTS_DIR)
            self.respond_json({"ok": True})
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

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
        if not download:
            self.send_error(404)
            return
        path = Path(download)
        if not path.exists():
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
        self.end_headers()
        self.wfile.write(data)

    def respond(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
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
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Customizable Transcription Interface running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
