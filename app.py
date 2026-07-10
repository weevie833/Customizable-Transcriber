from __future__ import annotations

import html
import json
import re
import threading
import urllib.parse
import zipfile
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from xml.etree import ElementTree

from transcription_bot.core import (
    DEFAULT_MODEL,
    TranscriptionConfig,
    count_failures,
    default_output_file,
    run_batch,
)


PROJECT_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
MAX_FORM_BYTES = 5_000_000
DEFAULT_PROFILE_ID = "rendi-battesimi"
PROFILES_DIR = PROJECT_DIR / "profiles"
PROFILE_SETTINGS_FILE = PROFILES_DIR / "settings.json"
SOURCE_FOLDER = Path("/Users/stevecovello/Desktop/MM/Transcription Sources")
MODELS = {
    "gemini-3.5-flash": "Gemini 3.5 Flash - faster / lower cost",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview - higher accuracy",
}

state = {
    "running": False,
    "log": [],
    "output": "",
    "download": "",
    "summary": "",
    "model": DEFAULT_MODEL,
    "order": "newest",
    "profile_id": DEFAULT_PROFILE_ID,
    "new_profile_name": "",
    "role_context": "",
    "reference_context": "",
    "output_format": "",
}
lock = threading.Lock()
stop_event = threading.Event()


def add_log(message: str) -> None:
    with lock:
        state["log"].append(message)
        state["log"] = state["log"][-300:]


def safe_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    clean = clean.strip(".-")
    return clean or "transcription-output.md"


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


def destination_output_file(profile_id: str) -> Path:
    return PROJECT_DIR / "outputs" / f"{safe_filename(profile_id)}-{output_stem()}.docx"


def selected_model(form: FormData) -> str:
    model = form.getfirst("model", DEFAULT_MODEL) or DEFAULT_MODEL
    if model not in MODELS:
        raise RuntimeError("Select a Gemini model before running transcription.")
    return model


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

def selected_profile_id(form: FormData) -> str:
    profile_id = form.getfirst("profile_id", DEFAULT_PROFILE_ID) or DEFAULT_PROFILE_ID
    if custom_profile_path(profile_id).exists():
        return profile_id
    return DEFAULT_PROFILE_ID


def profile_options_html(selected_profile: str) -> str:
    options = []
    for profile in load_custom_profiles():
        profile_id = html.escape(profile["id"])
        label = html.escape(profile["label"])
        selected = "selected" if selected_profile == profile["id"] else ""
        options.append(f'<option value="{profile_id}" {selected}>{label}</option>')
    return "\n".join(options)


def profiles_for_browser() -> dict[str, dict[str, str]]:
    return {
        profile["id"]: {
            "id": profile["id"],
            "label": profile["label"],
            "role_context": profile.get("role_context", ""),
            "reference_context": profile.get("reference_context", ""),
            "output_format": profile.get("output_format", ""),
        }
        for profile in load_custom_profiles()
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


def status_payload() -> dict[str, object]:
    with lock:
        return {
            "running": bool(state["running"]),
            "log": "\n".join(state["log"]),
            "output": str(state["output"]),
            "download": bool(state["download"]),
            "summary": str(state["summary"]),
        }


def page() -> str:
    with lock:
        running = bool(state["running"])
        log = "\n".join(state["log"])
        output = str(state["output"])
        download = str(state["download"])
        summary = str(state["summary"])
        model = str(state["model"])
        order = str(state["order"])
        profile_id = str(state["profile_id"])
        new_profile_name = str(state["new_profile_name"])
        role_context = str(state["role_context"])
        reference_context = str(state["reference_context"])
        output_format = str(state["output_format"])

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
    model_options = "\n".join(
        f'<option value="{html.escape(model_id)}" {"selected" if model == model_id else ""}>{html.escape(label)}</option>'
        for model_id, label in MODELS.items()
    )
    newest_checked = "checked" if order != "oldest" else ""
    oldest_checked = "checked" if order == "oldest" else ""
    profile_options = profile_options_html(profile_id)
    profile_data_json = json.dumps(profiles_for_browser()).replace("</", "<\\/")
    download_link = (
        '<a id="download-link" class="download" href="/download" download>Download Document</a>'
        if download
        else ""
    )

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
      document.getElementById("run-button").disabled = status.running;
      document.getElementById("stop-button").disabled = !status.running;

      const downloadWrap = document.getElementById("download-wrap");
      downloadWrap.innerHTML = status.download
        ? '<a id="download-link" class="download" href="/download" download>Download Document</a>'
        : "";

      if (status.running) {{
        window.setTimeout(refreshStatus, 1500);
      }}
    }}

    const profiles = {profile_data_json};
    let originalProfileFields = null;

    function profileFields() {{
      return {{
        role_context: document.querySelector('[name="role_context"]').value,
        reference_context: document.querySelector('[name="reference_context"]').value,
        output_format: document.querySelector('[name="output_format"]').value,
      }};
    }}

    function setProfileFields(profileId) {{
      const profile = profiles[profileId];
      if (!profile) return;
      document.querySelector('[name="role_context"]').value = profile.role_context || "";
      document.querySelector('[name="reference_context"]').value = profile.reference_context || "";
      document.querySelector('[name="output_format"]').value = profile.output_format || "";
      document.querySelector('[name="new_profile_name"]').value = "";
      document.querySelector('[name="profile_action"]').value = "use";
      const duplicateAction = document.querySelector('[name="duplicate_profile_action"]');
      if (duplicateAction) duplicateAction.value = "";
      originalProfileFields = profileFields();
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

    function setOrderHint() {{
      const selectedOrder = document.querySelector('[name="order"]:checked');
      const hint = document.getElementById("order-hint");
      if (!selectedOrder || !hint) return;
      hint.textContent = selectedOrder.value === "oldest"
        ? "Oldest-to-newest shows the oldest record at the top of the output document with newer entries following afterwards as you scroll."
        : "Newest-to-oldest shows the most recent record at the top of the output document with older entries following afterwards as you scroll.";
    }}

    function handleProfileEditsBeforeSubmit(event) {{
      const newName = document.querySelector('[name="new_profile_name"]').value.trim();
      const action = document.querySelector('[name="profile_action"]');
      if (event.submitter && event.submitter.id === "profile-save-button") {{
        action.value = newName ? "create" : "update";
        if (newName) resolveDuplicateProfileName(event, newName);
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
        profileSelect.addEventListener("change", () => setProfileFields(profileSelect.value));
      }}
      document.querySelectorAll('[name="order"]').forEach((input) => {{
        input.addEventListener("change", setOrderHint);
      }});
      setOrderHint();
      const runForm = document.querySelector('form[action="/run"]');
      if (runForm) {{
        runForm.addEventListener("submit", handleProfileEditsBeforeSubmit);
      }}
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
      max-width: 900px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    h1 {{
      margin: 0 0 20px;
      font-size: 28px;
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
    }}
    .tool-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}
    .profile-save-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
    }}
    .profile-save-row button {{
      margin-top: 0;
      white-space: nowrap;
    }}
    .tool-grid input {{
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }}
    .tool-grid span {{
      display: block;
      padding: 10px 12px;
      border: 1px solid #8d99a6;
      border-radius: 6px;
      text-align: center;
      font-weight: 700;
      cursor: pointer;
      background: #fff;
    }}
    .tool-grid input:checked + span {{
      border-color: #255c99;
      background: #255c99;
      color: #fff;
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
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
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
    .path-control button {{
      margin-top: 0;
      white-space: nowrap;
      background: #53616f;
    }}
    button:disabled {{
      background: #8d99a6;
      cursor: wait;
    }}
    pre {{
      min-height: 220px;
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
    .byline {{
      margin: -14px 0 20px;
      color: #5f6b76;
      font-size: 13px;
    }}
    .license {{
      margin: 8px 0 0;
      color: #5f6b76;
      font-size: 12px;
    }}
    @media (max-width: 720px) {{
      .row, .tool-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>Customizable Transcription Interface</h1>
  <p class="byline">Created by Steve Covello, 2026</p>
  <form method="post" action="/run">
    <div class="path-control">
      <label>Source folder
        <div class="path-display">{html.escape(str(SOURCE_FOLDER))}</div>
      </label>
    </div>
    <label>Gemini model
      <select name="model">
        {model_options}
      </select>
    </label>
    <label>Gemini API key
      <input type="password" name="gemini_api_key" autocomplete="off" placeholder="Paste your Gemini API key for this run">
      <p class="hint">Used only for this browser session/request. It is not saved to the project files.</p>
    </label>
    <label>Process order</label>
    <div class="tool-grid">
      <label><input type="radio" name="order" value="newest" required {newest_checked}><span>Newest-to-oldest</span></label>
      <label><input type="radio" name="order" value="oldest" required {oldest_checked}><span>Oldest-to-newest</span></label>
    </div>
    <p id="order-hint" class="hint"></p>
    <label>Prompt profile
      <select name="profile_id">
        {profile_options}
      </select>
      <input type="hidden" name="profile_action" value="use">
      <input type="hidden" name="duplicate_profile_action" value="">
      <p class="hint">The profile sections below are plain text fields. The app handles JSON formatting automatically when it saves, so quotes, brackets, and commas typed here will not break the profile file.</p>
    </label>
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
    <div class="actions">
      <button id="run-button" type="submit" {disabled}>Run transcription</button>
    </div>
  </form>
  <section class="panel">
    <div id="summary" class="summary">{escaped_summary}</div>
    <div class="actions">
      <form method="post" action="/stop">
        <button id="stop-button" class="danger" type="submit" {stop_disabled}>Stop</button>
      </form>
    </div>
    <p id="output">Output: {escaped_output}</p>
    <p><a href="/">Refresh Status</a></p>
    <div id="download-wrap">{download_link}</div>
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

        config = TranscriptionConfig(
            image_folder=image_folder,
            output_file=markdown_file,
            prompt_file=PROFILES_DIR,
            model=selected_model(form),
            delay_seconds=delay,
            reverse_order=form.getfirst("order", "newest") != "oldest",
            system_prompt=system_prompt,
            api_key_override=pasted_value(form, "gemini_api_key") or None,
        )
        results = run_batch(
            config,
            PROJECT_DIR,
            progress=add_log,
            cancel_requested=stop_event.is_set,
        )
        write_docx(output_file, markdown_file.read_text(encoding="utf-8"))
        failures = count_failures(results)
        with lock:
            if stop_event.is_set():
                state["summary"] = f"Stopped after {len(results)} image(s), {failures} failure(s)."
            else:
                state["summary"] = f"Processed {len(results)} image(s), {failures} failure(s)."
            state["download"] = str(output_file)
    except Exception as exc:
        add_log(f"Fatal error: {exc}")
        with lock:
            state["summary"] = f"Fatal error: {exc}"
    finally:
        with lock:
            state["running"] = False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/status":
            self.status()
            return

        if parsed.path == "/download":
            self.download()
            return

        if parsed.path != "/":
            self.redirect_home()
            return

        self.respond(page())

    def do_POST(self) -> None:
        if self.path == "/stop":
            self.stop_job()
            return

        if self.path == "/save-profile":
            self.save_profile()
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
        except Exception as exc:
            with lock:
                state["summary"] = f"Fatal error: {exc}"
                state["log"] = [f"Fatal error: {exc}"]
                state["download"] = ""
            self.respond(page())
            return

        order = form.getfirst("order", "newest")
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
            order = "newest"
        with lock:
            stop_event.clear()
            state["running"] = True
            state["log"] = []
            state["output"] = str(output_file)
            state["download"] = ""
            state["summary"] = f"Running {profile['label']}..."
            state["model"] = model
            state["order"] = order
            state["profile_id"] = profile_id
            state["new_profile_name"] = new_profile_name
            state["role_context"] = role_context
            state["reference_context"] = reference_context
            state["output_format"] = output_format

        thread = threading.Thread(target=run_job, args=(form, output_file), daemon=True)
        thread.start()
        self.respond(page())

    def save_profile(self) -> None:
        try:
            form = parse_post_form(self)
            profile_id = selected_profile_id(form)
            new_profile_name = pasted_value(form, "new_profile_name")
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

    def redirect_home(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    ensure_profiles_dir()
    with lock:
        state["profile_id"] = load_selected_profile_id()
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Customizable Transcription Interface running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
