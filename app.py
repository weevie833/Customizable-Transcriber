from __future__ import annotations

import html
import hashlib
import io
import json
import re
import secrets
import threading
import urllib.parse
import zipfile
from collections.abc import Mapping
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree

from transcription_bot.core import (
    DEFAULT_MODEL,
    FILE_TYPE_EXTENSIONS,
    TranscriptionConfig,
    count_failures,
    count_source_files_by_type,
    default_output_file,
    extensions_for_file_type,
    run_batch,
    validate_api_key,
)
from xls_conversion.ai_parser import parse_records_with_ai, preflight_records_with_ai
from test_mode.comparison import score_transcription


PROJECT_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
MAX_FORM_BYTES = 5_000_000
MAX_DOCX_BYTES = 50_000_000
MAX_JSON_BYTES = 15_000_000
DEFAULT_PROFILE_ID = "rendi-battesimi"
PROFILES_DIR = PROJECT_DIR / "profiles"
PROFILE_SETTINGS_FILE = PROFILES_DIR / "settings.json"
XLS_CONVERSION_DIR = PROJECT_DIR / "xls_conversion"
SOURCE_FOLDER = Path("/Users/stevecovello/Desktop/MM/Transcription Sources")
DOWNLOAD_HELP_TEXT = "The DOCX file will be downloaded to wherever your browser saves downloaded files. Check your browser's Downloads button for download history."
FILE_TYPE_LABELS = {
    "jpeg": "JPEG (.jpg, .jpeg)",
    "png": "PNG (.png)",
    "pdf": "PDF (.pdf)",
}
MODELS = {
    "gemini-3.6-flash": "Gemini 3.6 Flash - latest balanced speed / intelligence",
    "gemini-3.5-flash": "Gemini 3.5 Flash - faster / lower cost",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite - fastest / lowest cost",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite - frontier-class, low cost",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview - higher accuracy",
    "gemini-2.5-pro": "Gemini 2.5 Pro - stable, high-accuracy baseline",
}

state = {
    "running": False,
    "log": [],
    "output": "",
    "download": "",
    "summary": "",
    "model": DEFAULT_MODEL,
    "order": "oldest",
    "file_type": "jpeg",
    "profile_id": "",
    "new_profile_name": "",
    "role_context": "",
    "reference_context": "",
    "output_format": "",
}
lock = threading.Lock()
stop_event = threading.Event()
xls_preflight_lock = threading.Lock()
xls_preflight_cache: dict[str, dict[str, object]] = {}

def new_test_run_state() -> dict[str, str]:
    return {
        "batch_label": "",
        "label": "",
        "model": "",
        "output": "",
        "download": "",
        "markdown": "",
        "summary": "",
    }


test_state = {
    "running": False,
    "current_run_id": "",
    "log": [],
    "summary": "",
    "model_a": DEFAULT_MODEL,
    "model_b": DEFAULT_MODEL,
    "order": "oldest",
    "file_type": "jpeg",
    "profile_id": "",
    "queue": [],
    "runs": {},
}
test_lock = threading.Lock()
test_stop_event = threading.Event()


def add_log(message: str) -> None:
    with lock:
        state["log"].append(message)
        state["log"] = state["log"][-300:]


def add_test_log(message: str) -> None:
    with test_lock:
        test_state["log"].append(message)
        test_state["log"] = test_state["log"][-300:]


def safe_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    clean = clean.strip(".-")
    return clean or "transcription-output.md"


def output_stem() -> str:
    return default_output_file(PROJECT_DIR).stem


def reset_ui_state() -> None:
    with lock:
        state["running"] = False
        state["log"] = []
        state["output"] = ""
        state["download"] = ""
        state["summary"] = ""
        state["model"] = DEFAULT_MODEL
        state["order"] = "oldest"
        state["file_type"] = "jpeg"
        state["profile_id"] = ""
        state["new_profile_name"] = ""
        state["role_context"] = ""
        state["reference_context"] = ""
        state["output_format"] = ""


def reset_test_ui_state() -> None:
    with test_lock:
        test_state["running"] = False
        test_state["current_run_id"] = ""
        test_state["log"] = []
        test_state["summary"] = ""
        test_state["model_a"] = DEFAULT_MODEL
        test_state["model_b"] = DEFAULT_MODEL
        test_state["order"] = "oldest"
        test_state["file_type"] = "jpeg"
        test_state["profile_id"] = ""
        test_state["queue"] = []
        test_state["runs"] = {}


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
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError("The uploaded file is not a readable DOCX document.") from exc

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


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_xls_preflight(
    result: dict[str, object],
    record_type: str,
    text: str,
    image_range: str,
    model: str,
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
            "ok": result.get("ok") is True,
        }
    return token


def validate_xls_preflight(
    token: str,
    record_type: str,
    text: str,
    image_range: str,
    model: str,
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
    ):
        raise RuntimeError("The source or settings changed. Run preflight again before converting.")
    if preflight["ok"] is not True and not ignore_failure:
        raise RuntimeError("Preflight found missing images or English translations.")


def destination_output_file(profile_id: str) -> Path:
    return PROJECT_DIR / "outputs" / f"{safe_filename(profile_id)}-{output_stem()}.docx"


def test_destination_output_file(profile_id: str, run_id: str, model: str, stem: str) -> Path:
    return (
        PROJECT_DIR
        / "outputs"
        / f"{safe_filename(profile_id)}-{stem}-{safe_filename(run_id)}-{safe_filename(model)}.docx"
    )


def selected_model(form: FormData) -> str:
    model = form.getfirst("model", DEFAULT_MODEL) or DEFAULT_MODEL
    if model not in MODELS:
        raise RuntimeError("Select a Gemini model before running transcription.")
    return model


def selected_model_pair(form: FormData) -> tuple[str, str]:
    model_a = form.getfirst("model_a", DEFAULT_MODEL) or DEFAULT_MODEL
    model_b = form.getfirst("model_b", DEFAULT_MODEL) or DEFAULT_MODEL
    if model_a not in MODELS or model_b not in MODELS:
        raise RuntimeError("Select a Gemini model for both Model A and Model B before running.")
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


def preflight_source_file_type(source_folder: Path, file_type: str) -> int:
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


def profile_id_from_name(name: str) -> str:
    return safe_filename(name).lower() or "custom-profile"


def profile_path(profile_id: str) -> Path:
    return PROFILES_DIR / f"{profile_id}.json"


def custom_profile_path(profile_id: str) -> Path:
    return profile_path(profile_id)


def ensure_profiles_dir() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def split_profile_sections(text: str) -> tuple[str, str, str]:
    role_markers = ["# ROLE", "# TONE & STYLE"]
    reference_markers = ["# TECHNICAL REFERENCE: TAXONOMY"]
    output_markers = ["# PALEOGRAPHY REFERENCE: TRANSCRIPTION & TRANSLATION EXAMPLES", "# OUTPUT FORMAT"]

    reference_start = min((text.find(marker) for marker in reference_markers if text.find(marker) >= 0), default=-1)
    output_start = min((text.find(marker) for marker in output_markers if text.find(marker) >= 0), default=-1)

    section_starts = [index for index in (reference_start, output_start) if index >= 0]
    role_end = min(section_starts) if section_starts else len(text)
    role_context = text[:role_end].strip()

    reference_context = ""
    if reference_start >= 0:
        reference_end = output_start if output_start > reference_start else len(text)
        reference_context = text[reference_start:reference_end].strip()

    output_format = ""
    if output_start >= 0:
        output_format = text[output_start:].strip()

    if not role_context and any(marker in text for marker in role_markers):
        role_context = text.strip()
    return role_context, reference_context, output_format


def normalize_profile_sections(profile: dict[str, str]) -> dict[str, str]:
    role_context = str(profile.get("role_context", ""))
    reference_context = str(profile.get("reference_context", ""))
    output_format = str(profile.get("output_format", ""))
    if role_context and not reference_context and not output_format:
        role_context, reference_context, output_format = split_profile_sections(role_context)
        profile["role_context"] = role_context
        profile["reference_context"] = reference_context
        profile["output_format"] = output_format
    return profile


def write_profile(profile: dict[str, str]) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    custom_profile_path(profile["id"]).write_text(
        json.dumps(profile, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_saved_profiles() -> None:
    ensure_profiles_dir()
    for path in PROFILES_DIR.glob("*.json"):
        if path.name == PROFILE_SETTINGS_FILE.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        original = json.dumps(data, sort_keys=True)
        data = normalize_profile_sections(data)
        if json.dumps(data, sort_keys=True) != original:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

def load_selected_profile_id() -> str:
    ensure_profiles_dir()
    if not PROFILE_SETTINGS_FILE.exists():
        return DEFAULT_PROFILE_ID
    try:
        data = json.loads(PROFILE_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PROFILE_ID
    profile_id = str(data.get("selected_profile_id", DEFAULT_PROFILE_ID))
    if custom_profile_path(profile_id).exists():
        return profile_id
    return DEFAULT_PROFILE_ID


def save_selected_profile_id(profile_id: str) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_SETTINGS_FILE.write_text(
        json.dumps({"selected_profile_id": profile_id}, indent=2) + "\n",
        encoding="utf-8",
    )


def load_custom_profiles() -> list[dict[str, str]]:
    ensure_profiles_dir()
    profiles: list[dict[str, str]] = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        if path.name == PROFILE_SETTINGS_FILE.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data = normalize_profile_sections(data)
        profile_id = str(data.get("id") or path.stem)
        label = str(data.get("label") or profile_id)
        profiles.append({
            "id": profile_id,
            "label": label,
            "kind": str(data.get("kind", "custom")),
            "role_context": str(data.get("role_context", "")),
            "reference_context": str(data.get("reference_context", "")),
            "output_format": str(data.get("output_format", "")),
        })
    return profiles




def profile_version_suffix(profile_id: str) -> str:
    match = re.search(r"-(\d+)$", profile_id)
    if match:
        return f"Version {match.group(1)}"
    return "Original"


def profiles_with_display_labels() -> list[dict[str, str]]:
    profiles = load_custom_profiles()
    label_counts: dict[str, int] = {}
    for profile in profiles:
        key = profile["label"].strip().casefold()
        label_counts[key] = label_counts.get(key, 0) + 1

    for profile in profiles:
        key = profile["label"].strip().casefold()
        if label_counts.get(key, 0) > 1:
            profile["display_label"] = f"{profile['label']} ({profile_version_suffix(profile['id'])})"
        else:
            profile["display_label"] = profile["label"]
    return profiles

def load_profile(profile_id: str) -> dict[str, str]:
    for profile in load_custom_profiles():
        if profile["id"] == profile_id:
            profile["kind"] = "custom"
            return profile

    if profile_id != DEFAULT_PROFILE_ID:
        return load_profile(DEFAULT_PROFILE_ID)

    raise RuntimeError("No prompt profiles are available.")


def save_custom_profile(
    name: str,
    role_context: str,
    reference_context: str,
    output_format: str,
    replace_existing: bool = False,
) -> dict[str, str]:
    label = name.strip()
    if not label:
        raise RuntimeError("Enter a name before saving a new custom profile.")
    if not any((role_context, reference_context, output_format)):
        raise RuntimeError("Paste role, reference, or output-format content before saving a new custom profile.")

    profile_id = profile_id_from_name(label)
    if not replace_existing:
        base_id = profile_id
        counter = 2
        while custom_profile_path(profile_id).exists():
            profile_id = f"{base_id}-{counter}"
            counter += 1

    profile = {
        "id": profile_id,
        "label": label,
        "kind": "custom",
        "role_context": role_context,
        "reference_context": reference_context,
        "output_format": output_format,
    }
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    custom_profile_path(profile_id).write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    return profile


def update_profile(profile_id: str, role_context: str, reference_context: str, output_format: str) -> dict[str, str]:
    profile = load_profile(profile_id)
    profile["role_context"] = role_context
    profile["reference_context"] = reference_context
    profile["output_format"] = output_format
    write_profile(profile)
    return profile


def delete_profile(profile_id: str) -> dict[str, str]:
    profile = load_profile(profile_id)
    path = custom_profile_path(profile_id)
    if not path.exists():
        raise RuntimeError("Select a valid prompt profile before deleting.")
    path.unlink()
    if PROFILE_SETTINGS_FILE.exists():
        try:
            settings = json.loads(PROFILE_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}
        if settings.get("selected_profile_id") == profile_id:
            PROFILE_SETTINGS_FILE.unlink(missing_ok=True)
    return profile


def selected_profile_id(form: FormData) -> str:
    profile_id = form.getfirst("profile_id", "") or ""
    if not profile_id:
        raise RuntimeError("Select a prompt profile before running transcription.")
    if custom_profile_path(profile_id).exists():
        return profile_id
    raise RuntimeError("Select a valid prompt profile before running transcription.")


def profile_options_html(selected_profile: str) -> str:
    placeholder_selected = "selected" if not selected_profile else ""
    options = [f'<option value="" disabled {placeholder_selected}>Select a Profile</option>']
    for profile in profiles_with_display_labels():
        profile_id = html.escape(profile["id"])
        label = html.escape(profile["display_label"])
        selected = "selected" if selected_profile == profile["id"] else ""
        options.append(f'<option value="{profile_id}" {selected}>{label}</option>')
    return "\n".join(options)


def profiles_for_browser() -> dict[str, dict[str, str]]:
    return {
        profile["id"]: {
            "id": profile["id"],
            "label": profile.get("display_label", profile["label"]),
            "profile_label": profile["label"],
            "role_context": profile.get("role_context", ""),
            "reference_context": profile.get("reference_context", ""),
            "output_format": profile.get("output_format", ""),
        }
        for profile in profiles_with_display_labels()
    }

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
        "- Do not summarize, modernize, normalize, or invent missing words.\n"
        "- Use brackets for uncertain readings, for example [Rovella?] or [illegible].\n"
        "- If part of the page is unreadable, mark only that portion as [illegible].\n\n"
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



def output_status_text() -> str:
    if state["download"]:
        return "DOCX document ready."
    if state["running"] and state["output"]:
        return "DOCX document is being prepared."
    return ""


def status_payload() -> dict[str, object]:
    with lock:
        return {
            "running": bool(state["running"]),
            "log": "\n".join(state["log"]),
            "output": str(state["output"]),
            "download": bool(state["download"]),
            "completed": bool(state["download"]) and not bool(state["running"]),
            "summary": str(state["summary"]),
        }


def test_status_payload() -> dict[str, object]:
    with test_lock:
        runs = {
            run_id: {
                "batch_label": run["batch_label"],
                "label": run["label"],
                "model": run["model"],
                "summary": run["summary"],
                "download": bool(run["download"]),
            }
            for run_id, run in test_state["runs"].items()
        }
        all_complete = bool(runs) and all(run["download"] for run in test_state["runs"].values())
        return {
            "running": bool(test_state["running"]),
            "current_run_id": str(test_state["current_run_id"]),
            "log": "\n".join(test_state["log"]),
            "summary": str(test_state["summary"]),
            "completed": all_complete and not bool(test_state["running"]),
            "runs": runs,
        }


def page() -> str:
    with lock:
        running = bool(state["running"])
        log = "\n".join(state["log"])
        output = output_status_text()
        download = str(state["download"])
        summary = str(state["summary"])
        model = str(state["model"])
        order = str(state["order"])
        file_type = str(state["file_type"])
        profile_id = str(state["profile_id"])
        new_profile_name = str(state["new_profile_name"])
        role_context = str(state["role_context"])
        reference_context = str(state["reference_context"])
        output_format = str(state["output_format"])

    if profile_id:
        active_profile = load_profile(profile_id)
        if active_profile.get("kind") == "custom" and not any((role_context, reference_context, output_format)):
            role_context = active_profile.get("role_context", "")
            reference_context = active_profile.get("reference_context", "")
            output_format = active_profile.get("output_format", "")

    disabled = "disabled" if running else ""
    stop_disabled = "" if running else "disabled"
    escaped_log = html.escape(log)
    escaped_output = html.escape(output)
    escaped_summary = html.escape(summary)
    escaped_new_profile_name = html.escape(new_profile_name)
    escaped_role_context = html.escape(role_context)
    escaped_reference_context = html.escape(reference_context)
    escaped_output_format = html.escape(output_format)
    escaped_download_help = html.escape(DOWNLOAD_HELP_TEXT)
    model_options = "\n".join(
        f'<option value="{html.escape(model_id)}" {"selected" if model == model_id else ""}>{html.escape(label)}</option>'
        for model_id, label in MODELS.items()
    )
    newest_checked = "checked" if order == "newest" else ""
    oldest_checked = "checked" if order != "newest" else ""
    jpeg_checked = "checked" if file_type == "jpeg" else ""
    png_checked = "checked" if file_type == "png" else ""
    pdf_checked = "checked" if file_type == "pdf" else ""
    profile_options = profile_options_html(profile_id)
    profile_data_json = json.dumps(profiles_for_browser()).replace("</", "<\\/")
    download_disabled_class = "" if download else " disabled-link"
    download_aria_disabled = "false" if download else "true"

    return f"""<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Customizable Transcription Interface</title>
  <script>
    async function refreshStatus() {{
      const response = await fetch("/status", {{ cache: "no-store" }});
      if (!response.ok) return;
      const status = await response.json();
      document.getElementById("summary").textContent = status.summary || "";
      document.getElementById("output").textContent = "Output: " + (status.output || "");
      document.getElementById("log").textContent = status.log || "";
      updateRunButton(status.running);
      updateRunStatus(status.running);
      document.getElementById("stop-button").disabled = !status.running;
      updateDownloadControl(status.download);

      if (status.completed) {{
        showCompletionAlert();
      }}

      if (status.running) {{
        window.setTimeout(refreshStatus, 1500);
      }}
    }}

    const profiles = {profile_data_json};
    let originalProfileFields = null;
    let runConfirmed = false;
    let preflightComplete = false;
    let completionAlertShown = false;

    const downloadHelpText = "The DOCX file will be downloaded to wherever your browser saves downloaded files. Check your browser's Downloads button for download history.";

    function updateDownloadControl(available) {{
      const link = document.getElementById("download-link");
      if (!link) return;
      link.classList.toggle("disabled-link", !available);
      link.setAttribute("aria-disabled", available ? "false" : "true");
      link.tabIndex = available ? 0 : -1;
    }}

    function showCompletionAlert() {{
      if (completionAlertShown) return;
      completionAlertShown = true;
      showSettingsAlert("Batch completed. Scroll down and review the the Progress Console and click the Download Document button.");
    }}

    function profileFields() {{
      return {{
        role_context: document.querySelector('[name="role_context"]').value,
        reference_context: document.querySelector('[name="reference_context"]').value,
        output_format: document.querySelector('[name="output_format"]').value,
      }};
    }}

    function setProfileFields(profileId) {{
      const profile = profiles[profileId];
      if (!profile) {{
        document.querySelector('[name="role_context"]').value = "";
        document.querySelector('[name="reference_context"]').value = "";
        document.querySelector('[name="output_format"]').value = "";
        document.querySelector('[name="new_profile_name"]').value = "";
        document.querySelector('[name="profile_action"]').value = "use";
        originalProfileFields = profileFields();
        updateRunButton(false);
        updateDeleteButton(false);
        return;
      }}
      document.querySelector('[name="role_context"]').value = profile.role_context || "";
      document.querySelector('[name="reference_context"]').value = profile.reference_context || "";
      document.querySelector('[name="output_format"]').value = profile.output_format || "";
      document.querySelector('[name="new_profile_name"]').value = "";
      document.querySelector('[name="profile_action"]').value = "use";
      const duplicateAction = document.querySelector('[name="duplicate_profile_action"]');
      if (duplicateAction) duplicateAction.value = "";
      originalProfileFields = profileFields();
      updateRunButton(false);
      updateDeleteButton(false);
    }}

    function normalizeProfileName(name) {{
      return name.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "") || "custom-profile";
    }}

    function profileMatchingName(name) {{
      const normalizedName = normalizeProfileName(name);
      const loweredName = name.trim().toLowerCase();
      return Object.values(profiles).find((profile) =>
        profile.id === normalizedName || (profile.label || "").trim().toLowerCase() === loweredName
      );
    }}

    function suggestedVersionName(name) {{
      let counter = 2;
      let candidate = `${{name}} ${{counter}}`;
      while (profileMatchingName(candidate)) {{
        counter += 1;
        candidate = `${{name}} ${{counter}}`;
      }}
      return candidate;
    }}

    function resolveDuplicateProfileName(event, newName) {{
      const duplicate = profileMatchingName(newName);
      const duplicateAction = document.querySelector('[name="duplicate_profile_action"]');
      if (duplicateAction) duplicateAction.value = "";
      if (!duplicate) return true;

      if (window.confirm(`A profile named "${{duplicate.label}}" already exists. Choose OK to replace it, or Cancel to create a new version.`)) {{
        document.querySelector('[name="profile_id"]').value = duplicate.id;
        document.querySelector('[name="new_profile_name"]').value = "";
        document.querySelector('[name="profile_action"]').value = "update";
        if (duplicateAction) duplicateAction.value = "replace";
        return true;
      }}

      const versionName = window.prompt("Name for the new profile version:", suggestedVersionName(newName));
      if (!versionName || !versionName.trim()) {{
        event.preventDefault();
        return false;
      }}
      document.querySelector('[name="new_profile_name"]').value = versionName.trim();
      document.querySelector('[name="profile_action"]').value = "create";
      return true;
    }}

    function fieldsChanged() {{
      const current = profileFields();
      return originalProfileFields && (
        current.role_context !== originalProfileFields.role_context ||
        current.reference_context !== originalProfileFields.reference_context ||
        current.output_format !== originalProfileFields.output_format
      );
    }}


    function canRun() {{
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const apiKeyEntered = Boolean(document.querySelector('[name="gemini_api_key"]').value.trim());
      return profileSelected && apiKeyEntered;
    }}

    function playAlertSound() {{
      try {{
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        const context = new AudioContext();
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(660, context.currentTime);
        gain.gain.setValueAtTime(0.001, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.18, context.currentTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.28);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.3);
      }} catch (error) {{
        return;
      }}
    }}

    function showSettingsAlert(message) {{
      const alert = document.getElementById("settings-alert");
      const messageNode = document.getElementById("settings-alert-message");
      if (!alert || !messageNode) return;
      messageNode.textContent = message;
      alert.hidden = false;
      playAlertSound();
      const closeButton = document.getElementById("settings-alert-close");
      if (closeButton) closeButton.focus();
    }}

    function hideSettingsAlert() {{
      const alert = document.getElementById("settings-alert");
      if (alert) alert.hidden = true;
    }}

    function missingRunSettingMessage() {{
      const missing = [];
      if (!document.querySelector('[name="gemini_api_key"]').value.trim()) {{
        missing.push("paste a Gemini API key");
      }}
      if (!document.querySelector('[name="profile_id"]').value) {{
        missing.push("select a prompt profile");
      }}
      if (!missing.length) return "";
      if (missing.length === 1) return `Before running transcription, please ${{missing[0]}}.`;
      return "Before running transcription, please paste a Gemini API key and select a prompt profile.";
    }}

    function updateRunButton(running) {{
      const runButton = document.getElementById("run-button");
      if (!runButton) return;
      const confirmButton = document.getElementById("confirm-run-button");
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const apiKeyEntered = Boolean(document.querySelector('[name="gemini_api_key"]').value.trim());
      runButton.disabled = Boolean(running);
      if (confirmButton && running) confirmButton.disabled = true;
      if (running) {{
        runButton.title = "A transcription process is already running.";
      }} else if (!apiKeyEntered) {{
        runButton.title = "Paste your Gemini API key before running transcription.";
      }} else if (!profileSelected) {{
        runButton.title = "Select a prompt profile before running transcription.";
      }} else {{
        runButton.title = "Check selected settings before transcription.";
      }}
    }}

    function resetPreflight() {{
      runConfirmed = false;
      preflightComplete = false;
      const confirmButton = document.getElementById("confirm-run-button");
      const runButton = document.getElementById("run-button");
      const settings = document.getElementById("run-confirmation-settings");
      if (confirmButton) confirmButton.disabled = true;
      if (runButton) runButton.disabled = false;
      if (settings) settings.hidden = true;
    }}

    function selectedRunSettings() {{
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const selectedFileType = document.querySelector('[name="file_type"]:checked');
      const profileId = document.querySelector('[name="profile_id"]').value;
      const profile = profiles[profileId];
      const orderLabel = selectedOrder && selectedOrder.value === "oldest" ? "Oldest-to-newest" : "Newest-to-oldest";
      const fileTypeLabel = selectedFileType ? selectedFileType.value.toUpperCase() : "Not selected";
      const profileLabel = profile ? profile.profile_label || profile.label : "Select a Profile";
      return {{ orderLabel, fileTypeLabel, profileLabel }};
    }}

    function runPreflightCheck() {{
      const panel = document.getElementById("run-confirmation");
      if (!panel) return;
      const settings = selectedRunSettings();
      document.getElementById("confirm-order").textContent = settings.orderLabel;
      document.getElementById("confirm-file-type").textContent = settings.fileTypeLabel;
      document.getElementById("confirm-profile").textContent = settings.profileLabel;
      const settingsWrap = document.getElementById("run-confirmation-settings");
      const confirmButton = document.getElementById("confirm-run-button");
      const runButton = document.getElementById("run-button");
      if (settingsWrap) settingsWrap.hidden = false;
      if (confirmButton) confirmButton.disabled = false;
      if (runButton) runButton.disabled = true;
      preflightComplete = true;
    }}

    function updateRunStatus(running) {{
      const status = document.getElementById("run-status");
      const settings = document.getElementById("run-confirmation-settings");
      const title = document.querySelector("#run-confirmation .run-confirmation-title");
      if (!status) return;
      status.hidden = !running;
      if (settings && running) settings.hidden = true;
      if (title) title.textContent = running ? "Progress:" : "Confirm settings:";
    }}

    function updateDeleteButton(running) {{
      const deleteButton = document.getElementById("profile-delete-button");
      if (!deleteButton) return;
      deleteButton.disabled = Boolean(running) || !document.querySelector('[name="profile_id"]').value;
    }}

    function confirmProfileDelete(event) {{
      if (!event.submitter || event.submitter.id !== "profile-delete-button") return;
      const profileId = document.querySelector('[name="profile_id"]').value;
      const profile = profiles[profileId];
      const label = profile ? profile.label : "the selected profile";
      if (!window.confirm(`${{label}} will be permanently deleted. This cannot be undone.`)) {{
        event.preventDefault();
      }}
    }}

    function setOrderHint() {{
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const hint = document.getElementById("order-hint");
      if (!selectedOrder || !hint) return;
      hint.textContent = selectedOrder.value === "oldest"
        ? "Oldest-to-newest shows the oldest record at the top of the output document with newer entries following afterwards as you scroll."
        : "Newest-to-oldest shows the most recent record at the top of the output document with older entries following afterwards as you scroll.";
    }}

    function handleProfileEditsBeforeSubmit(event) {{
      if (event.submitter && event.submitter.id === "reset-button") return;
      if (event.submitter && event.submitter.id === "profile-delete-button") return;
      if (event.submitter && event.submitter.id === "run-button") {{
        const missingMessage = missingRunSettingMessage();
        if (missingMessage) {{
          event.preventDefault();
          resetPreflight();
          showSettingsAlert(missingMessage);
          return;
        }}
        event.preventDefault();
        runPreflightCheck();
        return;
      }}
      if (event.submitter && event.submitter.id === "confirm-run-button" && !preflightComplete) {{
        event.preventDefault();
        showSettingsAlert("Please run the preflight check before starting transcription.");
        return;
      }}
      if (event.submitter && event.submitter.id === "confirm-run-button") {{
        runConfirmed = false;
        preflightComplete = false;
      }}
      const newName = document.querySelector('[name="new_profile_name"]').value.trim();
      const action = document.querySelector('[name="profile_action"]');
      if (event.submitter && event.submitter.id === "profile-save-button") {{
        if (newName) {{
          action.value = "create";
          resolveDuplicateProfileName(event, newName);
          return;
        }}
        const profileId = document.querySelector('[name="profile_id"]').value;
        const profile = profiles[profileId];
        if (!profile) {{
          action.value = "update";
          return;
        }}
        if (window.confirm(`Replace "${{profile.label}}" with the current profile fields? Choose Cancel to save a new version.`)) {{
          action.value = "update";
          return;
        }}
        const versionName = window.prompt("Name for the new profile version:", suggestedVersionName(profile.profile_label || profile.label));
        if (!versionName || !versionName.trim()) {{
          event.preventDefault();
          return;
        }}
        document.querySelector('[name="new_profile_name"]').value = versionName.trim();
        action.value = "create";
        return;
      }}
      if (newName) {{
        action.value = "create";
        resolveDuplicateProfileName(event, newName);
        return;
      }}
      if (!fieldsChanged()) {{
        action.value = "use";
        return;
      }}
      if (window.confirm("Save these changes to the selected profile? Choose Cancel to save as a new version.")) {{
        action.value = "update";
        return;
      }}
      const versionName = window.prompt("Name for the new profile version:");
      if (!versionName || !versionName.trim()) {{
        event.preventDefault();
        return;
      }}
      document.querySelector('[name="new_profile_name"]').value = versionName.trim();
      action.value = "create";
    }}

    window.addEventListener("DOMContentLoaded", () => {{
      const profileSelect = document.querySelector('[name="profile_id"]');
      if (profileSelect) {{
        setProfileFields(profileSelect.value);
        profileSelect.addEventListener("change", () => {{
          setProfileFields(profileSelect.value);
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      const apiKeyInput = document.querySelector('[name="gemini_api_key"]');
      if (apiKeyInput) {{
        apiKeyInput.addEventListener("input", () => {{
          updateRunButton(false);
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      document.querySelectorAll('[name="order"]').forEach((input) => {{
        input.addEventListener("change", () => {{
          setOrderHint();
          resetPreflight();
        }});
      }});
      document.querySelectorAll('[name="file_type"]').forEach((input) => {{
        input.addEventListener("change", resetPreflight);
      }});
      setOrderHint();
      const confirmRunButton = document.getElementById("confirm-run-button");
      if (confirmRunButton) {{
        confirmRunButton.addEventListener("click", (event) => {{
          event.preventDefault();
          runConfirmed = true;
          completionAlertShown = false;
          if (runForm) runForm.requestSubmit(confirmRunButton);
        }});
      }}
      const downloadLink = document.getElementById("download-link");
      if (downloadLink) {{
        downloadLink.addEventListener("click", (event) => {{
          if (downloadLink.getAttribute("aria-disabled") === "true") event.preventDefault();
        }});
      }}
      const closeAlertButton = document.getElementById("settings-alert-close");
      if (closeAlertButton) {{
        closeAlertButton.addEventListener("click", hideSettingsAlert);
      }}
      const refreshStatusButton = document.getElementById("refresh-status-button");
      if (refreshStatusButton) {{
        refreshStatusButton.addEventListener("click", refreshStatus);
      }}
      const resetButton = document.getElementById("reset-button");
      if (resetButton) {{
        resetButton.addEventListener("click", () => {{
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      const runForm = document.querySelector('form[action="/run"]');
      if (runForm) {{
        runForm.addEventListener("submit", handleProfileEditsBeforeSubmit);
        runForm.addEventListener("submit", confirmProfileDelete);
      }}
      updateRunButton({str(running).lower()});
      updateRunStatus({str(running).lower()});
      updateDeleteButton({str(running).lower()});
      if ({str(running).lower()}) {{
        window.setTimeout(refreshStatus, 1500);
      }}
    }});
  </script>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    body {{
      margin: 0;
      background: #f7f5f0;
      color: #1f2933;
    }}
    main {{
      width: min(980px, calc(100% - 40px));
      margin: 0 auto;
      padding: 32px 0 48px;
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
    }}
    .site-header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: center;
      margin-bottom: 20px;
    }}
    .site-heading {{
      display: grid;
      gap: 4px;
    }}
    .site-nav {{
      display: flex;
      flex: 0 0 auto;
      gap: 4px;
      align-items: center;
    }}
    .nav-link {{
      display: inline-block;
      padding: 8px 10px 7px;
      border-bottom: 3px solid transparent;
      color: #255c99;
      font-weight: 650;
      text-decoration: none;
      white-space: nowrap;
    }}
    .nav-link:hover {{
      border-bottom-color: #9eb8d7;
      background: #eef4fb;
      color: #173f6d;
      text-decoration: underline;
      text-underline-offset: 3px;
    }}
    .nav-link:focus-visible {{
      outline: 3px solid #255c99;
      outline-offset: 2px;
      border-radius: 2px;
    }}
    .nav-link[aria-current="page"] {{
      border-bottom-color: #255c99;
      background: #e5eef9;
      color: #173f6d;
      font-weight: 750;
      text-decoration: none;
    }}
    form, .panel {{
      background: #ffffff;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 18px;
    }}
    label {{
      display: block;
      font-weight: 650;
      margin-top: 14px;
    }}
    input[type="text"], input[type="password"], input[type="number"], select, textarea {{
      box-sizing: border-box;
      width: 100%;
      margin-top: 6px;
      padding: 10px 12px;
      border: 1px solid #b8b2a5;
      border-radius: 6px;
      font: inherit;
      background: #fff;
      color: #1f2933;
    }}
    .path-control {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: end;
    }}
    .path-control button {{
      margin-top: 0;
      white-space: nowrap;
      background: #53616f;
    }}
    .path-display {{
      min-height: 22px;
      margin-top: 6px;
      overflow-wrap: anywhere;
      color: #4b5563;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px;
    }}
    textarea {{
      min-height: 140px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px;
      line-height: 1.45;
    }}
    .hint {{
      margin: 6px 0 0;
      color: #5f6b76;
      font-size: 13px;
      font-weight: 400;
    }}
    input[type="file"] {{
      display: none;
    }}
    .row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
      align-items: start;
    }}
    .run-options {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
      gap: 14px;
      align-items: start;
    }}
    .radio-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 8px;
    }}
    .profile-save-row, .profile-select-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
    }}
    .profile-save-row button, .profile-select-row button {{
      margin-top: 6px;
      white-space: nowrap;
    }}
    .radio-option {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 0;
      font-weight: 500;
      white-space: nowrap;
    }}
    .radio-option input {{
      margin: 0;
    }}
    .check {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 14px;
      font-weight: 500;
    }}
    .check input {{
      appearance: none;
      width: 16px;
      height: 16px;
      margin: 0;
      border: 1.5px solid #4b5563;
      border-radius: 2px;
      background: transparent;
    }}
    .check input:checked {{
      background: #255c99;
      border-color: #255c99;
      box-shadow: inset 0 0 0 3px #fff;
    }}
    button {{
      margin-top: 18px;
      padding: 10px 14px;
      border: 0;
      border-radius: 6px;
      background: #255c99;
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    button:not(:disabled):hover, .button-label:hover, .download:hover {{
      filter: brightness(0.92);
    }}
    button:not(:disabled):focus-visible, .button-label:focus-visible, .download:focus-visible {{
      outline: 3px solid rgba(37, 92, 153, 0.32);
      outline-offset: 2px;
    }}
    #reset-button, #profile-save-button, #refresh-status-button {{
      background: #255c99;
    }}
    #reset-button:not(:disabled):hover, #profile-save-button:not(:disabled):hover, #refresh-status-button:not(:disabled):hover {{
      background: #1f4d80;
      filter: none;
    }}
    #run-button {{
      background: #22863a;
    }}
    #run-button:not(:disabled):hover {{
      background: #176f2c;
    }}
    #run-button:disabled, #confirm-run-button:disabled {{
      background: #8d99a6;
      color: #eef2f6;
      cursor: not-allowed;
      opacity: 0.72;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .run-actions {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      margin-top: 22px;
    }}
    .run-button-stack {{
      display: grid;
      gap: 8px;
      align-items: start;
    }}
    .run-button-stack button {{
      width: 170px;
      margin-top: 0;
    }}
    .run-confirmation {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 10px;
      align-content: flex-start;
      align-items: flex-start;
      min-height: 72px;
      margin-top: 0;
      padding: 10px 12px;
      border: 1px solid #d9d4c8;
      border-radius: 6px;
      background: #fbfaf7;
      color: #1f2933;
      font-size: 13px;
    }}
    .profile-work-area {{
      margin: 20px -18px -18px;
      padding: 18px;
      border-top: 1px solid #d9d4c8;
      border-radius: 0 0 8px 8px;
      background: #f4f5f6;
    }}
    .profile-work-area > .hint:first-child {{
      margin-top: 0;
      margin-bottom: 12px;
    }}
    .profile-work-area > .hint:first-child + label {{
      margin-top: 0;
    }}
    .run-confirmation-settings[hidden] {{
      display: none;
    }}
    .run-confirmation-title {{
      font-weight: 700;
    }}
    .run-confirmation-settings {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      color: #4b5563;
    }}
    #confirm-run-button {{
      margin-top: 0;
      background: #22863a;
    }}
    .settings-alert {{
      position: fixed;
      inset: 0;
      z-index: 20;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(31, 41, 51, 0.34);
    }}
    .settings-alert[hidden] {{
      display: none;
    }}
    .settings-alert-box {{
      width: min(420px, 100%);
      padding: 20px;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 18px 42px rgba(31, 41, 51, 0.24);
      text-align: center;
    }}
    .settings-alert-title {{
      margin: 0 0 8px;
      font-size: 18px;
      font-weight: 750;
    }}
    .settings-alert-message {{
      margin: 0;
      color: #4b5563;
    }}
    #settings-alert-close {{
      margin-top: 16px;
    }}
    .run-status {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-top: 0;
      color: #37546b;
      font-size: 13px;
      font-weight: 650;
    }}
    .run-status[hidden] {{
      display: none;
    }}
    .spinner {{
      width: 16px;
      height: 16px;
      border: 2px solid #b8c2cc;
      border-top-color: #22863a;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }}
    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}
    .actions form {{
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .danger {{
      background: #a33a2b;
    }}
    #download-wrap {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .download-note {{
      color: #5f6b76;
      font-size: 13px;
    }}
    .button-label, .download {{
      display: inline-block;
      margin-top: 0;
      padding: 10px 14px;
      border: 0;
      border-radius: 6px;
      background: #53616f;
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      white-space: nowrap;
    }}
    .download {{
      background: #22863a;
    }}
    .download:not(.disabled-link):hover {{
      background: #176f2c;
      filter: none;
    }}
    .download.disabled-link {{
      background: #8d99a6;
      color: #eef2f6;
      cursor: not-allowed;
      opacity: 0.72;
      pointer-events: none;
    }}
    #download-link {{
      margin-top: 18px;
    }}
    .button-secondary {{
      margin-top: 8px;
      background: #255c99;
    }}
    button:disabled {{
      background: #8d99a6;
      cursor: not-allowed;
    }}
    pre {{
      min-height: 150px;
      max-height: 200px;
      overflow: auto;
      white-space: pre-wrap;
      background: #15191f;
      color: #e8edf2;
      border-radius: 8px;
      padding: 14px;
    }}
    .summary {{
      color: #37546b;
      font-weight: 650;
    }}
    .panel-title {{
      margin: 0 0 10px;
      font-size: 16px;
    }}
    .byline {{
      margin: 0;
      color: #5f6b76;
      font-size: 13px;
    }}
    .license {{
      margin: 8px 0 0;
      color: #5f6b76;
      font-size: 12px;
    }}
    @media (max-width: 720px) {{
      main {{
        width: min(100% - 28px, 980px);
        padding-top: 20px;
      }}
      .row, .run-options, .profile-select-row, .profile-save-row {{ grid-template-columns: 1fr; }}
      .path-control {{ grid-template-columns: 1fr; }}
      .run-actions {{ grid-template-columns: 1fr; }}
      .site-header {{ align-items: stretch; }}
      .run-button-stack button {{ width: 100%; }}
    }}
    @media (max-width: 520px) {{
      .site-header {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
<div id="settings-alert" class="settings-alert" role="alertdialog" aria-modal="true" aria-labelledby="settings-alert-title" hidden>
  <div class="settings-alert-box">
    <p id="settings-alert-title" class="settings-alert-title">Run settings needed</p>
    <p id="settings-alert-message" class="settings-alert-message"></p>
    <button id="settings-alert-close" type="button">OK</button>
  </div>
</div>
<main>
  <header class="site-header">
    <div class="site-heading">
      <h1>Customizable Transcription Interface</h1>
      <p class="byline">Created by Steve Covello, 2026</p>
    </div>
    <nav class="site-nav" aria-label="Primary navigation">
      <a class="nav-link" href="/" aria-current="page">Transcribe</a>
      <a class="nav-link" href="/xls-conversion">XLS Conversion</a>
      <a class="nav-link" href="/test-mode">Test Mode</a>
    </nav>
  </header>
  <form method="post" action="/run">
    <div class="path-control">
      <label>Source folder
        <div class="path-display">{html.escape(str(SOURCE_FOLDER))}</div>
      </label>
      <button id="reset-button" type="submit" formaction="/reset" formmethod="post" {disabled}>Reset</button>
    </div>
    <div class="row">
      <label>Gemini model
        <select name="model">
          {model_options}
        </select>
      </label>
      <label>Gemini API key
        <input type="password" name="gemini_api_key" autocomplete="off" placeholder="Paste your Gemini API key for this run">
        <p class="hint">Used only for this browser session/request. It is not saved to the project files.</p>
      </label>
    </div>
    <div class="run-options">
      <div>
        <label>Process order</label>
        <div class="radio-row">
          <label class="radio-option"><input type="radio" name="order" value="oldest" required {oldest_checked}>Oldest-to-newest</label>
          <label class="radio-option"><input type="radio" name="order" value="newest" required {newest_checked}>Newest-to-oldest</label>
        </div>
        <p id="order-hint" class="hint"></p>
      </div>
      <div>
        <label>File type</label>
        <div class="radio-row">
          <label class="radio-option"><input type="radio" name="file_type" value="jpeg" required {jpeg_checked}>JPEG</label>
          <label class="radio-option"><input type="radio" name="file_type" value="png" required {png_checked}>PNG</label>
          <label class="radio-option"><input type="radio" name="file_type" value="pdf" required {pdf_checked}>PDF</label>
        </div>
        <p class="hint">JPEG includes .jpg and .jpeg files.</p>
      </div>
    </div>
    <label>Prompt profile
      <div class="profile-select-row">
        <select name="profile_id">
          {profile_options}
        </select>
        <button id="profile-delete-button" class="danger" type="submit" formaction="/delete-profile" formmethod="post" disabled>Delete Profile</button>
      </div>
      <input type="hidden" name="profile_action" value="use">
      <input type="hidden" name="duplicate_profile_action" value="">
    </label>
    <div class="actions run-actions">
      <div class="run-button-stack">
        <button id="run-button" type="submit" disabled>Preflight Check</button>
        <button id="confirm-run-button" type="submit" disabled>Confirm and run</button>
      </div>
      <span id="run-confirmation" class="run-confirmation">
        <span class="run-confirmation-title">Confirm settings:</span>
        <span id="run-confirmation-settings" class="run-confirmation-settings" hidden>
          <span>Order: <strong id="confirm-order"></strong></span>
          <span>File type: <strong id="confirm-file-type"></strong></span>
          <span>Prompt Profile: <strong id="confirm-profile"></strong></span>
        </span>
        <span id="run-status" class="run-status" hidden><span class="spinner" aria-hidden="true"></span>Process running. Review the Progress Console below.</span>
      </span>
    </div>
    <div class="profile-work-area">
      <p class="hint">The profile sections below are plain text fields. The app handles JSON formatting automatically when it saves, so quotes, brackets, and commas typed here will not break the profile file.</p>
      <label>Save new custom profile as
      <p class="hint">Leave blank to update the selected profile. Enter a new name to save the three boxes below as a reusable profile.</p>
      <div class="profile-save-row">
        <input type="text" name="new_profile_name" value="{escaped_new_profile_name}" placeholder="Example: Palermo baptisms">
        <button id="profile-save-button" type="submit" formaction="/save-profile" formmethod="post" {disabled}>Save Profile</button>
      </div>
      </label>
      <label>Role and local context
      <p class="hint">Plain text. Shows the profile role plus tone and style. Edit this box to update the selected profile or create a new version when you run transcription.</p>
      <textarea name="role_context" placeholder="Example: You are an expert paleographer specializing in 18th-century Palermo, Sicily baptism records...">{escaped_role_context}</textarea>
      </label>
      <label>Ground truth and reference material
      <p class="hint">Plain text. Shows the profile technical reference, taxonomy, dictionaries, names, places, formulas, and ground truth material.</p>
      <textarea name="reference_context" placeholder="Paste reference content here">{escaped_reference_context}</textarea>
      </label>
      <label>Output format
      <p class="hint">Plain text. Shows the profile output structure and transcription/translation examples.</p>
      <textarea name="output_format" placeholder="Paste output format here">{escaped_output_format}</textarea>
      </label>
    </div>
  </form>
  <section class="panel">
    <h2 class="panel-title">Progress Console</h2>
    <div id="summary" class="summary">{escaped_summary}</div>
    <div class="actions">
      <form method="post" action="/stop">
        <button id="stop-button" class="danger" type="submit" {stop_disabled}>Stop</button>
      </form>
      <a id="download-link" class="download{download_disabled_class}" href="/download" download aria-disabled="{download_aria_disabled}">Download Document</a>
      <span class="download-note">{escaped_download_help}</span>
    </div>
    <p id="output">Output: {escaped_output}</p>
    <button id="refresh-status-button" class="button-secondary" type="button">Refresh Status</button>
    <pre id="log">{escaped_log}</pre>
  </section>
  <footer class="license">Created under Creative Commons license Attribution-NonCommercial-ShareAlike (CC BY-NC-SA). Not for commercial use. Attribution required.</footer>
</main>
</body>
</html>"""


def test_mode_page() -> str:
    with test_lock:
        running = bool(test_state["running"])
        log = "\n".join(test_state["log"])
        summary = str(test_state["summary"])
        model_a = str(test_state["model_a"])
        model_b = str(test_state["model_b"])
        order = str(test_state["order"])
        file_type = str(test_state["file_type"])
        profile_id = str(test_state["profile_id"])
        queue = [dict(batch) for batch in test_state["queue"]]
        runs = {run_id: dict(run) for run_id, run in test_state["runs"].items()}

    disabled = "disabled" if running else ""
    stop_disabled = "" if running else "disabled"
    escaped_log = html.escape(log)
    escaped_summary = html.escape(summary)

    def model_options_for(selected: str) -> str:
        return "\n".join(
            f'<option value="{html.escape(model_id)}" {"selected" if selected == model_id else ""}>{html.escape(label)}</option>'
            for model_id, label in MODELS.items()
        )

    model_a_options = model_options_for(model_a)
    model_b_options = model_options_for(model_b)

    newest_checked = "checked" if order == "newest" else ""
    oldest_checked = "checked" if order != "newest" else ""
    jpeg_checked = "checked" if file_type == "jpeg" else ""
    png_checked = "checked" if file_type == "png" else ""
    pdf_checked = "checked" if file_type == "pdf" else ""
    profile_options = profile_options_html(profile_id)
    profile_data_json = json.dumps(profiles_for_browser()).replace("</", "<\\/")
    model_labels_json = json.dumps(MODELS).replace("</", "<\\/")
    initial_runs_json = json.dumps(runs).replace("</", "<\\/")

    queue_list_html = "\n".join(
        f'''<li class="queue-item">
          <span>{html.escape(batch["label"])}: {html.escape(MODELS.get(batch["model_a"], batch["model_a"]))}
            vs {html.escape(MODELS.get(batch["model_b"], batch["model_b"]))}</span>
          <button type="submit" class="danger queue-remove-button" formaction="/test-mode/queue/remove" formmethod="post" formnovalidate name="batch_id" value="{html.escape(batch["batch_id"])}" {disabled}>Remove</button>
        </li>'''
        for batch in queue
    ) or '<li class="queue-empty hint">No batches queued yet. Click "Add to Batch" to queue the Model A/B pair above, or leave the queue empty and just run this one pair directly.</li>'

    return f"""<!doctype html>
<html lang="en">
  <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Test Mode - Model Comparison</title>
  <script>
    const profiles = {profile_data_json};
    const MODEL_LABELS = {model_labels_json};
    const initialRuns = {initial_runs_json};
    const queueLength = {len(queue)};
    let runConfirmed = false;
    let preflightComplete = false;
    let completionAlertShown = false;
    let extraFileCount = 0;

    function modelLabelFor(modelId) {{
      return MODEL_LABELS[modelId] || modelId || "";
    }}

    function escapeHtml(value) {{
      const div = document.createElement("div");
      div.textContent = value === null || value === undefined ? "" : String(value);
      return div.innerHTML;
    }}

    function renderRunRows(runs) {{
      const container = document.getElementById("progress-rows");
      if (!container) return;
      const runIds = Object.keys(runs || {{}});
      if (!runIds.length) {{
        container.innerHTML = '<p class="hint">No runs yet.</p>';
        return;
      }}
      container.innerHTML = "";
      runIds.forEach((runId) => {{
        const run = runs[runId];
        const available = Boolean(run.download);
        const row = document.createElement("div");
        row.className = "run-row";
        row.innerHTML =
          '<div class="run-row-label">' + escapeHtml(run.label || runId) + " &mdash; " + escapeHtml(modelLabelFor(run.model)) + "</div>" +
          '<div class="run-row-summary">' + escapeHtml(run.summary || "") + "</div>" +
          '<a class="download' + (available ? "" : " disabled-link") + '" href="/test-mode/download/' + encodeURIComponent(runId) + '" download aria-disabled="' + (available ? "false" : "true") + '">Download DOCX</a>';
        const link = row.querySelector("a");
        link.addEventListener("click", (event) => {{
          if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
        }});
        container.appendChild(row);
      }});
    }}

    async function refreshStatus() {{
      const response = await fetch("/test-mode/status", {{ cache: "no-store" }});
      if (!response.ok) return;
      const status = await response.json();
      document.getElementById("summary").textContent = status.summary || "";
      document.getElementById("log").textContent = status.log || "";
      updateRunButton(status.running);
      updateRunStatus(status.running);
      document.getElementById("stop-button").disabled = !status.running;
      renderRunRows(status.runs);

      if (status.completed) {{
        showCompletionAlert();
      }}

      if (status.running) {{
        window.setTimeout(refreshStatus, 1500);
      }}
    }}

    function showCompletionAlert() {{
      if (completionAlertShown) return;
      completionAlertShown = true;
      showSettingsAlert("Both runs completed. Scroll down and review the Progress Console and download each model's document.");
    }}

    function playAlertSound() {{
      try {{
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        const context = new AudioContext();
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(660, context.currentTime);
        gain.gain.setValueAtTime(0.001, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.18, context.currentTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.28);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.3);
      }} catch (error) {{
        return;
      }}
    }}

    function showSettingsAlert(message) {{
      const alert = document.getElementById("settings-alert");
      const messageNode = document.getElementById("settings-alert-message");
      if (!alert || !messageNode) return;
      messageNode.textContent = message;
      alert.hidden = false;
      playAlertSound();
      const closeButton = document.getElementById("settings-alert-close");
      if (closeButton) closeButton.focus();
    }}

    function hideSettingsAlert() {{
      const alert = document.getElementById("settings-alert");
      if (alert) alert.hidden = true;
    }}

    function missingRunSettingMessage() {{
      const missing = [];
      if (!document.querySelector('[name="gemini_api_key"]').value.trim()) {{
        missing.push("paste a Gemini API key");
      }}
      if (!document.querySelector('[name="profile_id"]').value) {{
        missing.push("select a prompt profile");
      }}
      if (!missing.length) return "";
      if (missing.length === 1) return `Before running transcription, please ${{missing[0]}}.`;
      return "Before running transcription, please paste a Gemini API key and select a prompt profile.";
    }}

    function updateRunButton(running) {{
      const runButton = document.getElementById("run-button");
      if (!runButton) return;
      const confirmButton = document.getElementById("confirm-run-button");
      const profileSelected = Boolean(document.querySelector('[name="profile_id"]').value);
      const apiKeyEntered = Boolean(document.querySelector('[name="gemini_api_key"]').value.trim());
      runButton.disabled = Boolean(running);
      if (confirmButton && running) confirmButton.disabled = true;
      if (running) {{
        runButton.title = "A test run is already in progress.";
      }} else if (!apiKeyEntered) {{
        runButton.title = "Paste your Gemini API key before running.";
      }} else if (!profileSelected) {{
        runButton.title = "Select a prompt profile before running.";
      }} else {{
        runButton.title = "Check selected settings before running.";
      }}
    }}

    function resetPreflight() {{
      runConfirmed = false;
      preflightComplete = false;
      const confirmButton = document.getElementById("confirm-run-button");
      const runButton = document.getElementById("run-button");
      const settings = document.getElementById("run-confirmation-settings");
      if (confirmButton) confirmButton.disabled = true;
      if (runButton) runButton.disabled = false;
      if (settings) settings.hidden = true;
    }}

    function selectedRunSettings() {{
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const selectedFileType = document.querySelector('[name="file_type"]:checked');
      const profileId = document.querySelector('[name="profile_id"]').value;
      const profile = profiles[profileId];
      const modelASelect = document.querySelector('[name="model_a"]');
      const modelBSelect = document.querySelector('[name="model_b"]');
      const orderLabel = selectedOrder && selectedOrder.value === "oldest" ? "Oldest-to-newest" : "Newest-to-oldest";
      const fileTypeLabel = selectedFileType ? selectedFileType.value.toUpperCase() : "Not selected";
      const profileLabel = profile ? profile.profile_label || profile.label : "Select a Profile";
      const modelALabel = modelASelect ? modelASelect.options[modelASelect.selectedIndex].text : "";
      const modelBLabel = modelBSelect ? modelBSelect.options[modelBSelect.selectedIndex].text : "";
      const batchSummary = queueLength > 0
        ? queueLength + " queued batch" + (queueLength === 1 ? "" : "es")
        : modelALabel + " vs " + modelBLabel;
      return {{ orderLabel, fileTypeLabel, profileLabel, modelALabel, modelBLabel, batchSummary }};
    }}

    function runPreflightCheck() {{
      const panel = document.getElementById("run-confirmation");
      if (!panel) return;
      const settings = selectedRunSettings();
      document.getElementById("confirm-order").textContent = settings.orderLabel;
      document.getElementById("confirm-file-type").textContent = settings.fileTypeLabel;
      document.getElementById("confirm-profile").textContent = settings.profileLabel;
      document.getElementById("confirm-batches").textContent = settings.batchSummary;
      const settingsWrap = document.getElementById("run-confirmation-settings");
      const confirmButton = document.getElementById("confirm-run-button");
      const runButton = document.getElementById("run-button");
      if (settingsWrap) settingsWrap.hidden = false;
      if (confirmButton) confirmButton.disabled = false;
      if (runButton) runButton.disabled = true;
      preflightComplete = true;
    }}

    function updateRunStatus(running) {{
      const status = document.getElementById("run-status");
      const settings = document.getElementById("run-confirmation-settings");
      const title = document.querySelector("#run-confirmation .run-confirmation-title");
      if (!status) return;
      status.hidden = !running;
      if (settings && running) settings.hidden = true;
      if (title) title.textContent = running ? "Progress:" : "Confirm settings:";
    }}

    function updateDeleteButton(running) {{
      const deleteButton = document.getElementById("profile-delete-button");
      if (!deleteButton) return;
      deleteButton.disabled = Boolean(running) || !document.querySelector('[name="profile_id"]').value;
    }}

    function confirmProfileDelete(event) {{
      if (!event.submitter || event.submitter.id !== "profile-delete-button") return;
      const profileId = document.querySelector('[name="profile_id"]').value;
      const profile = profiles[profileId];
      const label = profile ? profile.label : "the selected profile";
      if (!window.confirm(`${{label}} will be permanently deleted. This cannot be undone.`)) {{
        event.preventDefault();
      }}
    }}

    function setOrderHint() {{
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const hint = document.getElementById("order-hint");
      if (!selectedOrder || !hint) return;
      hint.textContent = selectedOrder.value === "oldest"
        ? "Oldest-to-newest shows the oldest record at the top of each output document with newer entries following afterwards as you scroll."
        : "Newest-to-oldest shows the most recent record at the top of each output document with older entries following afterwards as you scroll.";
    }}

    function excludeSelectedValue(sourceSelect, targetSelect) {{
      const sourceValue = sourceSelect.value;
      let targetChanged = false;
      Array.from(targetSelect.options).forEach((option) => {{
        option.disabled = option.value === sourceValue;
      }});
      if (targetSelect.value === sourceValue) {{
        const fallback = Array.from(targetSelect.options).find((option) => !option.disabled);
        if (fallback) {{
          targetSelect.value = fallback.value;
          targetChanged = true;
        }}
      }}
      return targetChanged;
    }}

    function syncModelSelects() {{
      const selectA = document.querySelector('[name="model_a"]');
      const selectB = document.querySelector('[name="model_b"]');
      if (!selectA || !selectB) return;
      excludeSelectedValue(selectA, selectB);
      excludeSelectedValue(selectB, selectA);
    }}

    function handleProfileEditsBeforeSubmit(event) {{
      if (event.submitter && event.submitter.id === "reset-button") return;
      if (event.submitter && event.submitter.id === "profile-delete-button") return;
      if (event.submitter && event.submitter.id === "add-to-batch-button") return;
      if (event.submitter && event.submitter.id === "run-button") {{
        const missingMessage = missingRunSettingMessage();
        if (missingMessage) {{
          event.preventDefault();
          resetPreflight();
          showSettingsAlert(missingMessage);
          return;
        }}
        event.preventDefault();
        runPreflightCheck();
        return;
      }}
      if (event.submitter && event.submitter.id === "confirm-run-button" && !preflightComplete) {{
        event.preventDefault();
        showSettingsAlert("Please run the preflight check before starting.");
        return;
      }}
      if (event.submitter && event.submitter.id === "confirm-run-button") {{
        runConfirmed = false;
        preflightComplete = false;
      }}
    }}

    function formatPercent(fraction) {{
      return (fraction * 100).toFixed(2) + "%";
    }}

    function renderCompareResults(results) {{
      const container = document.getElementById("compare-results");
      container.innerHTML = "";
      if (!results || !results.length) {{
        container.innerHTML = '<p class="hint">No results.</p>';
        return;
      }}
      const table = document.createElement("table");
      table.className = "compare-table";
      const header = document.createElement("tr");
      header.innerHTML = "<th>Rank</th><th>Contestant</th><th>CER</th><th>WER</th><th>WER-BoW</th><th>Quality</th>";
      table.appendChild(header);
      results.forEach((entry) => {{
        const row = document.createElement("tr");
        if (entry.rank === 1) row.className = "compare-row-winner";
        const modelText = entry.model ? " (" + escapeHtml(modelLabelFor(entry.model)) + ")" : "";
        row.innerHTML =
          "<td>" + entry.rank + "</td>" +
          "<td>" + escapeHtml(entry.label) + modelText + "</td>" +
          "<td>" + formatPercent(entry.cer) + "</td>" +
          "<td>" + formatPercent(entry.wer) + "</td>" +
          "<td>" + formatPercent(entry.wer_bow) + "</td>" +
          "<td>" + escapeHtml(entry.quality) + "</td>";
        table.appendChild(row);
      }});
      container.appendChild(table);
    }}

    function addExtraFileRow() {{
      const container = document.getElementById("extra-model-files");
      if (!container) return;
      extraFileCount++;
      const row = document.createElement("div");
      row.className = "extra-file-row";
      row.innerHTML =
        '<input type="text" placeholder="Label for this model" data-extra-label>' +
        '<input type="file" accept=".docx" data-extra-file>' +
        '<button type="button" class="danger extra-file-remove">Remove</button>';
      row.querySelector(".extra-file-remove").addEventListener("click", () => row.remove());
      container.appendChild(row);
    }}

    async function runCompare() {{
      const button = document.getElementById("run-compare-button");
      const status = document.getElementById("compare-file-status");
      const container = document.getElementById("compare-results");
      const correctedFile = document.getElementById("corrected-file-input").files[0];
      if (!correctedFile) {{
        if (status) status.textContent = "Upload the 100% Corrected DOCX before comparing.";
        return;
      }}

      const body = new FormData();
      body.append("corrected_file", correctedFile);

      let extraCount = 0;
      document.querySelectorAll("#extra-model-files .extra-file-row").forEach((row) => {{
        const fileInput = row.querySelector("[data-extra-file]");
        const file = fileInput && fileInput.files[0];
        if (!file) return;
        const labelInput = row.querySelector("[data-extra-label]");
        const label = (labelInput && labelInput.value.trim()) || ("Uploaded model " + extraCount);
        body.append("extra_model_file_" + extraCount, file);
        body.append("extra_model_label_" + extraCount, label);
        extraCount += 1;
      }});

      if (extraCount === 0) {{
        if (status) status.textContent = "Add at least one model DOCX to compare.";
        return;
      }}

      button.disabled = true;
      if (status) status.textContent = "Comparing...";
      container.innerHTML = "";
      try {{
        const response = await fetch("/api/test-mode/compare", {{ method: "POST", body }});
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Comparison failed.");
        renderCompareResults(data.results);
        if (status) status.textContent = "";
      }} catch (error) {{
        container.innerHTML = '<p class="hint">' + escapeHtml(error.message || "Comparison failed.") + "</p>";
        if (status) status.textContent = "";
      }} finally {{
        button.disabled = false;
      }}
    }}

    window.addEventListener("DOMContentLoaded", () => {{
      const profileSelect = document.querySelector('[name="profile_id"]');
      if (profileSelect) {{
        profileSelect.addEventListener("change", () => {{
          updateRunButton(false);
          updateDeleteButton(false);
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      const apiKeyInput = document.querySelector('[name="gemini_api_key"]');
      if (apiKeyInput) {{
        apiKeyInput.addEventListener("input", () => {{
          updateRunButton(false);
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      document.querySelectorAll('[name="order"]').forEach((input) => {{
        input.addEventListener("change", () => {{
          setOrderHint();
          resetPreflight();
        }});
      }});
      document.querySelectorAll('[name="file_type"]').forEach((input) => {{
        input.addEventListener("change", resetPreflight);
      }});
      document.querySelectorAll('[name="model_a"], [name="model_b"]').forEach((input) => {{
        input.addEventListener("change", () => {{
          syncModelSelects();
          resetPreflight();
        }});
      }});
      syncModelSelects();
      setOrderHint();
      const confirmRunButton = document.getElementById("confirm-run-button");
      if (confirmRunButton) {{
        confirmRunButton.addEventListener("click", (event) => {{
          event.preventDefault();
          runConfirmed = true;
          completionAlertShown = false;
          if (runForm) runForm.requestSubmit(confirmRunButton);
        }});
      }}
      const closeAlertButton = document.getElementById("settings-alert-close");
      if (closeAlertButton) {{
        closeAlertButton.addEventListener("click", hideSettingsAlert);
      }}
      const refreshStatusButton = document.getElementById("refresh-status-button");
      if (refreshStatusButton) {{
        refreshStatusButton.addEventListener("click", refreshStatus);
      }}
      const resetButton = document.getElementById("reset-button");
      if (resetButton) {{
        resetButton.addEventListener("click", () => {{
          resetPreflight();
          hideSettingsAlert();
        }});
      }}
      const addExtraFileButton = document.getElementById("add-extra-file-button");
      if (addExtraFileButton) {{
        addExtraFileButton.addEventListener("click", addExtraFileRow);
      }}
      const runCompareButton = document.getElementById("run-compare-button");
      if (runCompareButton) {{
        runCompareButton.addEventListener("click", runCompare);
      }}
      const runForm = document.querySelector('form[action="/test-mode/run"]');
      if (runForm) {{
        runForm.addEventListener("submit", handleProfileEditsBeforeSubmit);
        runForm.addEventListener("submit", confirmProfileDelete);
      }}
      renderRunRows(initialRuns);
      updateRunButton({str(running).lower()});
      updateRunStatus({str(running).lower()});
      updateDeleteButton({str(running).lower()});
      if ({str(running).lower()}) {{
        window.setTimeout(refreshStatus, 1500);
      }}
    }});
  </script>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    body {{
      margin: 0;
      background: #f7f5f0;
      color: #1f2933;
    }}
    main {{
      width: min(980px, calc(100% - 40px));
      margin: 0 auto;
      padding: 32px 0 48px;
    }}
    h1 {{
      margin: 0;
      font-size: 28px;
    }}
    .site-header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: center;
      margin-bottom: 20px;
    }}
    .site-heading {{
      display: grid;
      gap: 4px;
    }}
    .site-nav {{
      display: flex;
      flex: 0 0 auto;
      gap: 4px;
      align-items: center;
    }}
    .nav-link {{
      display: inline-block;
      padding: 8px 10px 7px;
      border-bottom: 3px solid transparent;
      color: #255c99;
      font-weight: 650;
      text-decoration: none;
      white-space: nowrap;
    }}
    .nav-link:hover {{
      border-bottom-color: #9eb8d7;
      background: #eef4fb;
      color: #173f6d;
      text-decoration: underline;
      text-underline-offset: 3px;
    }}
    .nav-link:focus-visible {{
      outline: 3px solid #255c99;
      outline-offset: 2px;
      border-radius: 2px;
    }}
    .nav-link[aria-current="page"] {{
      border-bottom-color: #255c99;
      background: #e5eef9;
      color: #173f6d;
      font-weight: 750;
      text-decoration: none;
    }}
    form, .panel {{
      background: #ffffff;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 18px;
    }}
    label {{
      display: block;
      font-weight: 650;
      margin-top: 14px;
    }}
    input[type="text"], input[type="password"], input[type="number"], select, textarea {{
      box-sizing: border-box;
      width: 100%;
      margin-top: 6px;
      padding: 10px 12px;
      border: 1px solid #b8b2a5;
      border-radius: 6px;
      font: inherit;
      background: #fff;
      color: #1f2933;
    }}
    input[type="file"]::file-selector-button {{
      margin-right: 8px;
      padding: 6px 10px;
      border: 1px solid #b8b2a5;
      border-radius: 6px;
      font: inherit;
      font-size: 13px;
      background: #f4f5f6;
      color: #1f2933;
      cursor: pointer;
    }}
    input[type="file"]::file-selector-button:hover {{
      background: #e9eaec;
    }}
    .path-control {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: end;
    }}
    .path-control button {{
      margin-top: 0;
      white-space: nowrap;
      background: #53616f;
    }}
    .path-display {{
      min-height: 22px;
      margin-top: 6px;
      overflow-wrap: anywhere;
      color: #4b5563;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px;
    }}
    textarea {{
      min-height: 140px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px;
      line-height: 1.45;
    }}
    .hint {{
      margin: 6px 0 0;
      color: #5f6b76;
      font-size: 13px;
      font-weight: 400;
    }}
    .row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
      align-items: start;
    }}
    .run-options {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
      gap: 14px;
      align-items: start;
    }}
    .radio-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 8px;
    }}
    .profile-save-row, .profile-select-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
    }}
    .profile-save-row button, .profile-select-row button {{
      margin-top: 6px;
      white-space: nowrap;
    }}
    .radio-option {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 0;
      font-weight: 500;
      white-space: nowrap;
    }}
    .radio-option input {{
      margin: 0;
    }}
    button {{
      margin-top: 18px;
      padding: 10px 14px;
      border: 0;
      border-radius: 6px;
      background: #255c99;
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    button:not(:disabled):hover, .button-label:hover, .download:hover {{
      filter: brightness(0.92);
    }}
    button:not(:disabled):focus-visible, .button-label:focus-visible, .download:focus-visible {{
      outline: 3px solid rgba(37, 92, 153, 0.32);
      outline-offset: 2px;
    }}
    #reset-button, #profile-save-button, #refresh-status-button {{
      background: #255c99;
    }}
    #reset-button:not(:disabled):hover, #profile-save-button:not(:disabled):hover, #refresh-status-button:not(:disabled):hover {{
      background: #1f4d80;
      filter: none;
    }}
    #run-button {{
      background: #22863a;
    }}
    #run-button:not(:disabled):hover {{
      background: #176f2c;
    }}
    #run-button:disabled, #confirm-run-button:disabled {{
      background: #8d99a6;
      color: #eef2f6;
      cursor: not-allowed;
      opacity: 0.72;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    .run-actions {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      margin-top: 22px;
    }}
    .run-button-stack {{
      display: grid;
      gap: 8px;
      align-items: start;
    }}
    .run-button-stack button {{
      width: 170px;
      margin-top: 0;
    }}
    .run-confirmation {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 10px;
      align-content: flex-start;
      align-items: flex-start;
      min-height: 72px;
      margin-top: 0;
      padding: 10px 12px;
      border: 1px solid #d9d4c8;
      border-radius: 6px;
      background: #fbfaf7;
      color: #1f2933;
      font-size: 13px;
    }}
    .profile-work-area {{
      margin: 20px -18px -18px;
      padding: 18px;
      border-top: 1px solid #d9d4c8;
      border-radius: 0 0 8px 8px;
      background: #f4f5f6;
    }}
    .profile-work-area > .hint:first-child {{
      margin-top: 0;
      margin-bottom: 12px;
    }}
    .profile-work-area > .hint:first-child + label {{
      margin-top: 0;
    }}
    .run-confirmation-settings[hidden] {{
      display: none;
    }}
    .run-confirmation-title {{
      font-weight: 700;
    }}
    .run-confirmation-settings {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      color: #4b5563;
    }}
    #confirm-run-button {{
      margin-top: 0;
      background: #22863a;
    }}
    .settings-alert {{
      position: fixed;
      inset: 0;
      z-index: 20;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(31, 41, 51, 0.34);
    }}
    .settings-alert[hidden] {{
      display: none;
    }}
    .settings-alert-box {{
      width: min(420px, 100%);
      padding: 20px;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 18px 42px rgba(31, 41, 51, 0.24);
      text-align: center;
    }}
    .settings-alert-title {{
      margin: 0 0 8px;
      font-size: 18px;
      font-weight: 750;
    }}
    .settings-alert-message {{
      margin: 0;
      color: #4b5563;
    }}
    #settings-alert-close {{
      margin-top: 16px;
    }}
    .run-status {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-top: 0;
      color: #37546b;
      font-size: 13px;
      font-weight: 650;
    }}
    .run-status[hidden] {{
      display: none;
    }}
    .spinner {{
      width: 16px;
      height: 16px;
      border: 2px solid #b8c2cc;
      border-top-color: #22863a;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }}
    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}
    .actions form {{
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .danger {{
      background: #a33a2b;
    }}
    .download-note {{
      color: #5f6b76;
      font-size: 13px;
    }}
    .button-label, .download {{
      display: inline-block;
      margin-top: 0;
      padding: 10px 14px;
      border: 0;
      border-radius: 6px;
      background: #53616f;
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      white-space: nowrap;
    }}
    .download {{
      background: #22863a;
    }}
    .download:not(.disabled-link):hover {{
      background: #176f2c;
      filter: none;
    }}
    .download.disabled-link {{
      background: #8d99a6;
      color: #eef2f6;
      cursor: not-allowed;
      opacity: 0.72;
      pointer-events: none;
    }}
    .button-secondary {{
      margin-top: 8px;
      background: #255c99;
    }}
    button:disabled {{
      background: #8d99a6;
      cursor: not-allowed;
    }}
    pre {{
      min-height: 150px;
      max-height: 200px;
      overflow: auto;
      white-space: pre-wrap;
      background: #15191f;
      color: #e8edf2;
      border-radius: 8px;
      padding: 14px;
    }}
    .summary {{
      color: #37546b;
      font-weight: 650;
    }}
    .panel-title {{
      margin: 0 0 10px;
      font-size: 16px;
    }}
    .byline {{
      margin: 0;
      color: #5f6b76;
      font-size: 13px;
    }}
    .license {{
      margin: 8px 0 0;
      color: #5f6b76;
      font-size: 12px;
    }}
    .queue-list {{
      list-style: none;
      margin: 6px 0 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .queue-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 12px;
      border: 1px solid #d9d4c8;
      border-radius: 6px;
      background: #fbfaf7;
      font-size: 13px;
    }}
    .queue-item form {{
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .queue-remove-button {{
      margin-top: 0;
      padding: 6px 10px;
      font-size: 12px;
    }}
    .queue-empty {{
      list-style: none;
      padding: 8px 0 0;
    }}
    .progress-rows {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }}
    .run-row {{
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 12px;
      align-items: center;
      padding: 10px 14px;
      border: 1px solid #d9d4c8;
      border-radius: 8px;
      background: #fbfaf7;
    }}
    .run-row-label {{
      font-weight: 650;
      font-size: 13px;
    }}
    .run-row-summary {{
      color: #4b5563;
      font-size: 13px;
    }}
    .run-row .download {{
      margin-top: 0;
    }}
    .extra-file-row {{
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 10px;
      align-items: center;
      margin-top: 8px;
    }}
    .extra-file-row input {{
      margin-top: 0;
    }}
    .extra-file-remove {{
      margin-top: 0;
      padding: 6px 10px;
      font-size: 12px;
    }}
    .button-tiny {{
      margin-top: 10px;
      padding: 5px 10px;
      border: 1px solid #255c99;
      background: #fff;
      color: #255c99;
      font-size: 12px;
      font-weight: 650;
    }}
    .button-tiny:not(:disabled):hover {{
      background: #eef4fb;
      filter: none;
    }}
    #add-to-batch-button {{
      margin-top: 6px;
    }}
    #refresh-status-button {{
      margin-top: 18px;
    }}
    .compare-table {{
      width: 100%;
      margin-top: 14px;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .compare-table th, .compare-table td {{
      border: 1px solid #d9d4c8;
      padding: 8px 10px;
      text-align: left;
    }}
    .compare-table th {{
      background: #f4f5f6;
      font-weight: 650;
    }}
    .compare-row-winner {{
      background: #eef7ef;
      font-weight: 650;
    }}
    @media (max-width: 720px) {{
      main {{
        width: min(100% - 28px, 980px);
        padding-top: 20px;
      }}
      .row, .run-options, .profile-select-row, .profile-save-row, .run-row, .extra-file-row {{ grid-template-columns: 1fr; }}
      .path-control {{ grid-template-columns: 1fr; }}
      .run-actions {{ grid-template-columns: 1fr; }}
      .site-header {{ align-items: stretch; }}
      .run-button-stack button {{ width: 100%; }}
    }}
    @media (max-width: 520px) {{
      .site-header {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
<div id="settings-alert" class="settings-alert" role="alertdialog" aria-modal="true" aria-labelledby="settings-alert-title" hidden>
  <div class="settings-alert-box">
    <p id="settings-alert-title" class="settings-alert-title">Run settings needed</p>
    <p id="settings-alert-message" class="settings-alert-message"></p>
    <button id="settings-alert-close" type="button">OK</button>
  </div>
</div>
<main>
  <header class="site-header">
    <div class="site-heading">
      <h1>Test Mode: Model Comparison</h1>
      <p class="byline">Created by Steve Covello, 2026</p>
    </div>
    <nav class="site-nav" aria-label="Primary navigation">
      <a class="nav-link" href="/">Transcribe</a>
      <a class="nav-link" href="/xls-conversion">XLS Conversion</a>
      <a class="nav-link" href="/test-mode" aria-current="page">Test Mode</a>
    </nav>
  </header>
  <p class="hint">Runs the same source images and prompt profile through different Gemini models to compare performance.</p>
  <form method="post" action="/test-mode/run">
    <div class="path-control">
      <label>Source folder
        <div class="path-display">{html.escape(str(SOURCE_FOLDER))}</div>
      </label>
      <button id="reset-button" type="submit" formaction="/test-mode/reset" formmethod="post" {disabled}>Reset</button>
    </div>
    <div class="row">
      <label>Model A
        <select name="model_a">
          {model_a_options}
        </select>
      </label>
      <label>Model B
        <select name="model_b">
          {model_b_options}
        </select>
      </label>
    </div>
    <div class="row">
      <label>Batch label (optional)
        <input type="text" name="batch_label" placeholder="Example: Flash-Lite vs 3.6 Flash">
      </label>
      <label>&nbsp;<br>
        <button id="add-to-batch-button" type="submit" formaction="/test-mode/queue/add" formmethod="post" {disabled}>Add to Batch</button>
      </label>
    </div>
    <label>Batch queue
      <ul class="queue-list">
        {queue_list_html}
      </ul>
    </label>
    <label>Gemini API key
      <input type="password" name="gemini_api_key" autocomplete="off" placeholder="Paste your Gemini API key for this run">
      <p class="hint">Used for every run in the queue. Not saved to the project files.</p>
    </label>
    <div class="run-options">
      <div>
        <label>Process order</label>
        <div class="radio-row">
          <label class="radio-option"><input type="radio" name="order" value="oldest" required {oldest_checked}>Oldest-to-newest</label>
          <label class="radio-option"><input type="radio" name="order" value="newest" required {newest_checked}>Newest-to-oldest</label>
        </div>
        <p id="order-hint" class="hint"></p>
      </div>
      <div>
        <label>File type</label>
        <div class="radio-row">
          <label class="radio-option"><input type="radio" name="file_type" value="jpeg" required {jpeg_checked}>JPEG</label>
          <label class="radio-option"><input type="radio" name="file_type" value="png" required {png_checked}>PNG</label>
          <label class="radio-option"><input type="radio" name="file_type" value="pdf" required {pdf_checked}>PDF</label>
        </div>
        <p class="hint">JPEG includes .jpg and .jpeg files.</p>
      </div>
    </div>
    <label>Prompt profile
      <div class="profile-select-row">
        <select name="profile_id">
          {profile_options}
        </select>
        <button id="profile-delete-button" class="danger" type="submit" formaction="/test-mode/delete-profile" formmethod="post" disabled>Delete Profile</button>
      </div>
      <input type="hidden" name="profile_action" value="use">
      <input type="hidden" name="duplicate_profile_action" value="">
      <input type="hidden" name="new_profile_name" value="">
      <p class="hint">Test Mode runs the profile as saved &mdash; edit or create profiles from the Transcribe page.</p>
    </label>
    <div class="actions run-actions">
      <div class="run-button-stack">
        <button id="run-button" type="submit" disabled>Preflight Check</button>
        <button id="confirm-run-button" type="submit" disabled>Confirm and run</button>
      </div>
      <span id="run-confirmation" class="run-confirmation">
        <span class="run-confirmation-title">Confirm settings:</span>
        <span id="run-confirmation-settings" class="run-confirmation-settings" hidden>
          <span>Batches: <strong id="confirm-batches"></strong></span>
          <span>Order: <strong id="confirm-order"></strong></span>
          <span>File type: <strong id="confirm-file-type"></strong></span>
          <span>Prompt Profile: <strong id="confirm-profile"></strong></span>
        </span>
        <span id="run-status" class="run-status" hidden><span class="spinner" aria-hidden="true"></span>Process running. Review the Progress Console below.</span>
      </span>
    </div>
  </form>
  <section class="panel">
    <h2 class="panel-title">Compare Results</h2>
    <p class="hint">Upload uncorrected DOCX transcripts to compare to a corrected DOCX.</p>
    <div id="extra-model-files">
      <div class="extra-file-row">
        <input type="text" placeholder="Label for this model" data-extra-label>
        <input type="file" accept=".docx" data-extra-file>
      </div>
      <div class="extra-file-row">
        <input type="text" placeholder="Label for this model" data-extra-label>
        <input type="file" accept=".docx" data-extra-file>
      </div>
    </div>
    <button id="add-extra-file-button" class="button-tiny" type="button">Add another</button>
    <label>100% Corrected DOCX</label>
    <div class="extra-file-row">
      <input type="text" placeholder="Label for this model">
      <input type="file" id="corrected-file-input" accept=".docx">
    </div>
    <p id="compare-file-status" class="hint"></p>
    <div class="actions">
      <button id="run-compare-button" class="button-secondary" type="button">Run Comparison</button>
      <span class="hint">Compare the quality of each transcript against a fully corrected version of the same content. Results will display different types of error rates.</span>
    </div>
    <div id="compare-results"></div>
  </section>
  <section class="panel">
    <h2 class="panel-title">Progress Console</h2>
    <div id="summary" class="summary">{escaped_summary}</div>
    <div class="actions">
      <form method="post" action="/test-mode/stop">
        <button id="stop-button" class="danger" type="submit" {stop_disabled}>Stop</button>
      </form>
      <button id="refresh-status-button" class="button-secondary" type="button">Refresh Status</button>
    </div>
    <div id="progress-rows" class="progress-rows"></div>
    <pre id="log">{escaped_log}</pre>
  </section>
  <footer class="license">Created under Creative Commons license Attribution-NonCommercial-ShareAlike (CC BY-NC-SA). Not for commercial use. Attribution required.</footer>
</main>
</body>
</html>"""


def paragraph(text: str) -> ElementTree.Element:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = ElementTree.Element(f"{{{ns}}}p")
    r = ElementTree.SubElement(p, f"{{{ns}}}r")
    t = ElementTree.SubElement(r, f"{{{ns}}}t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return p


def content_types_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""


def root_rels_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def document_xml(text: str) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ElementTree.register_namespace("w", ns)
    document = ElementTree.Element(f"{{{ns}}}document")
    body = ElementTree.SubElement(document, f"{{{ns}}}body")
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


def write_docx(output_docx: Path, text: str) -> None:
    output_docx.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_docx, "w", zipfile.ZIP_DEFLATED) as output:
        output.writestr("[Content_Types].xml", content_types_xml())
        output.writestr("_rels/.rels", root_rels_xml())
        output.writestr("word/document.xml", document_xml(text))


def run_job(form: FormData, output_file: Path) -> None:
    try:
        image_folder = SOURCE_FOLDER
        file_type = selected_file_type(form)
        markdown_file = PROJECT_DIR / "outputs" / f"{output_file.stem}.md"
        delay = 2.0
        profile = resolve_profile_for_run(form)
        system_prompt = build_system_prompt(
            tool="generic",
            profile=profile,
        )
        save_selected_profile_id(profile["id"])
        if profile.get("kind") == "custom":
            add_log(f"Using custom prompt profile: {profile['label']}")
        else:
            add_log(f"Using prompt profile: {profile['label']}")

        source_count = preflight_source_file_type(image_folder, file_type)
        add_log(f"Found {source_count} {file_type_display(file_type)} source file(s) for this run.")

        add_log("Checking Gemini API key before starting image processing...")
        validate_api_key(
            PROJECT_DIR,
            selected_model(form),
            pasted_value(form, "gemini_api_key") or None,
        )
        add_log("Gemini API key validated.")

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
            write_docx(output_file, markdown_file.read_text(encoding="utf-8"))
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
    run_specs: list[tuple[str, str, str, Path, Path]],
) -> None:
    """Run every queued (batch, model) pair's full image batch, one after another.

    run_specs is (run_id, label, model, markdown_file, output_file). Each
    iteration is an independent run_batch() call: its own TranscriptionConfig,
    its own markdown/docx output files, and its own fresh Gemini client
    (created inside run_batch via make_client). Nothing from one run — its
    output text, its log, anything — is read back into another run's prompt
    or config, so every run in the queue is unaffected by whatever the others
    produced, no matter how many pairs are queued.
    """
    try:
        image_folder = SOURCE_FOLDER
        file_type = selected_file_type(form)
        profile = resolve_profile_for_run(form)
        system_prompt = build_system_prompt(tool="generic", profile=profile)
        save_selected_profile_id(profile["id"])
        if profile.get("kind") == "custom":
            add_test_log(f"Using custom prompt profile: {profile['label']}")
        else:
            add_test_log(f"Using prompt profile: {profile['label']}")

        source_count = preflight_source_file_type(image_folder, file_type)
        add_test_log(f"Found {source_count} {file_type_display(file_type)} source file(s) for this run.")

        api_key_value = pasted_value(form, "gemini_api_key") or None
        reverse_order = form.getfirst("order", "oldest") != "oldest"

        for run_id, label, model, markdown_file, output_file in run_specs:
            if test_stop_event.is_set():
                add_test_log(f"Stopped before {label} started.")
                break

            with test_lock:
                test_state["current_run_id"] = run_id

            tag = f"[{label}: {model}]"
            add_test_log(f"{tag} Checking Gemini API key before starting image processing...")
            validate_api_key(PROJECT_DIR, model, api_key_value)
            add_test_log(f"{tag} Gemini API key validated. Starting run.")

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
                write_docx(output_file, markdown_file.read_text(encoding="utf-8"))
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
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in {"/xls-conversion", "/xls-conversion/"}:
            self.serve_xls_asset("index.html")
            return

        if parsed.path.startswith("/xls-conversion/"):
            self.serve_xls_asset(parsed.path.removeprefix("/xls-conversion/"))
            return

        if parsed.path == "/status":
            self.status()
            return

        if parsed.path == "/download":
            self.download()
            return

        if parsed.path in {"/test-mode", "/test-mode/"}:
            self.respond(test_mode_page())
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

        self.respond(page())

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path == "/api/xls-conversion/upload":
            self.upload_xls_source()
            return

        if urllib.parse.urlparse(self.path).path == "/api/xls-conversion/parse":
            self.parse_xls_source()
            return

        if urllib.parse.urlparse(self.path).path == "/api/xls-conversion/preflight":
            self.preflight_xls_source()
            return

        if urllib.parse.urlparse(self.path).path == "/api/test-mode/compare":
            self.compare_test()
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
            if state["running"]:
                self.respond(page())
                return

        try:
            form = parse_post_form(self)
            model = selected_model(form)
            api_key_value = pasted_value(form, "gemini_api_key")
            if not api_key_value:
                raise RuntimeError("Paste a Gemini API key before running transcription.")
            selected_profile_id(form)
            preflight_source_file_type(SOURCE_FOLDER, selected_file_type(form))
        except Exception as exc:
            with lock:
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
            save_selected_profile_id(profile_id)
            form.setfirst("profile_id", profile_id)
            form.setfirst("profile_action", "use")
            form.setfirst("new_profile_name", "")
        except Exception as exc:
            with lock:
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
                raise RuntimeError("Select a Gemini model before converting.")
            api_key_value = str(payload.get("gemini_api_key", "") or "").strip()
            if not api_key_value:
                raise RuntimeError("Paste a Gemini API key before converting.")
            record_type = str(payload.get("record_type", "") or "")
            text = str(payload.get("text", "") or "")
            image_range = str(payload.get("image_range", "") or "")
            validate_xls_preflight(
                token=str(payload.get("preflight_token", "") or ""),
                record_type=record_type,
                text=text,
                image_range=image_range,
                model=model,
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
            )
            self.respond_json(result)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, status=400)

    def preflight_xls_source(self) -> None:
        try:
            payload = parse_json_body(self)
            model = str(payload.get("model", "") or "")
            if model not in MODELS:
                raise RuntimeError("Select a Gemini model before running preflight.")
            api_key_value = str(payload.get("gemini_api_key", "") or "").strip()
            if not api_key_value:
                raise RuntimeError("Paste a Gemini API key before running preflight.")
            record_type = str(payload.get("record_type", "") or "")
            text = str(payload.get("text", "") or "")
            image_range = str(payload.get("image_range", "") or "")
            validate_api_key(PROJECT_DIR, model, api_key_value)
            result = preflight_records_with_ai(
                record_type=record_type,
                text=text,
                image_range=image_range,
                api_key=api_key_value,
                model=model,
            )
            token = save_xls_preflight(result, record_type, text, image_range, model)
            result["preflight_token"] = token
            result["source_hash"] = source_hash(text)
            self.respond_json(result)
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
            save_selected_profile_id(profile["id"])
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

    def delete_profile(self) -> None:
        with lock:
            if state["running"]:
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
                self.redirect_home()
                return
        stop_event.clear()
        reset_ui_state()
        self.redirect_home()

    def add_to_queue(self) -> None:
        with test_lock:
            if test_state["running"]:
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
            if test_state["running"]:
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
            if test_state["running"]:
                self.respond(test_mode_page())
                return

        try:
            form = parse_post_form(self)
            api_key_value = pasted_value(form, "gemini_api_key")
            if not api_key_value:
                raise RuntimeError("Paste a Gemini API key before running transcription.")
            file_type = selected_file_type(form)
            preflight_source_file_type(SOURCE_FOLDER, file_type)
            batches = resolve_run_batches(form)
            profile = resolve_profile_for_run(form)
            profile_id = profile["id"]
            save_selected_profile_id(profile_id)
        except Exception as exc:
            with test_lock:
                test_state["summary"] = f"Fatal error: {exc}"
                test_state["log"] = [f"Fatal error: {exc}"]
            self.respond(test_mode_page())
            return

        order = form.getfirst("order", "oldest")
        if order not in {"newest", "oldest"}:
            order = "oldest"

        stem = output_stem()
        run_specs: list[tuple[str, str, str, Path, Path]] = []
        runs_init: dict[str, dict[str, str]] = {}
        for batch in batches:
            for slot, model in (("a", batch["model_a"]), ("b", batch["model_b"])):
                run_id = f"{batch['batch_id']}-{slot}"
                label = f"{batch['label']} · Model {slot.upper()}"
                output_file = test_destination_output_file(profile_id, run_id, model, stem)
                markdown_file = PROJECT_DIR / "outputs" / f"{output_file.stem}.md"
                run_specs.append((run_id, label, model, markdown_file, output_file))
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
            if test_state["running"]:
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

    def redirect_test_mode(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/test-mode")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    ensure_profiles_dir()
    with lock:
        state["profile_id"] = ""
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Customizable Transcription Interface running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
