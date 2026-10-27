"""Prompt-profile storage: where profiles live on disk, and every load/save/
update/delete/import/export operation on them. Split out of app.py as part
of the app.py-modularization pass (see docs/DESIGN.md's "Codebase
structure" section) -- this was the single largest cohesive concern still
sitting in app.py's own module scope, with its own well-defined boundary
(nothing here reads an HTTP request directly; app.py's own
selected_profile_id()/resolve_profile_for_run() stay there for exactly that
reason -- profile_options_html()/profiles_for_browser() moved here too in a
later pass once pages/*.py also needed them, since both depend on nothing
but this module's own data).

Also owns PROJECT_DIR and safe_filename() -- not because they're profile-
specific, but because profile path resolution needs them and moving them
here (with app.py importing them back) was simpler and safer than the
alternative of either duplicating them or creating an app.py <-> here
circular import. PROJECT_DIR resolves identically regardless of which
repo-root module computes it (Path(__file__).resolve().parent), so this
isn't a behavior change, just a change in which file owns the name.

USER_OUTPUTS_DIR and APP_SETTINGS_FILE are NOT here -- they're not profile
data, they're app.py's own concerns (generated output, remembered source
folder), built from USER_DATA_DIR in app.py itself. Likewise, this module's
ensure_profiles_dir() only sets up the profile directories and runs the
one-time legacy-name-rename migration; app.py's own outputs/settings
migration is a separate function there.
"""

from __future__ import annotations

import html
import json
import os
import platform
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Guards every profile-store mutation (create/update/delete) against the
# request-thread concurrency this app's ThreadingHTTPServer makes real, not
# just theoretical -- see CODEX_REVIEW.md finding M-4. atomic_write_text()
# already prevents a *corrupt* (truncated/interleaved) file; this lock
# closes a different gap it doesn't: two near-simultaneous creates each
# independently probing find_profile_path() for a free id (the "-2"/"-3"
# auto-suffix loop in save_custom_profile()) could otherwise both see the
# same id as free and race to write it, silently losing one profile. It
# does NOT add optimistic conflict detection for two browser tabs
# genuinely editing the same already-saved profile -- last-writer-wins is
# preserved there deliberately, since resolving that needs a revision
# token and a conflict UI, a product decision this fix doesn't make on its
# own.
_profile_write_lock = threading.Lock()


def safe_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    clean = clean.strip(".-")
    return clean or "transcription-output.md"


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write text to `path` via write-temp-then-replace, instead of
    Path.write_text()'s write-in-place with no atomicity guarantee at all --
    a crash, a full disk, or (this app runs on ThreadingHTTPServer, so it's
    a real possibility, not just theoretical) two near-simultaneous saves of
    the same profile from two request threads could otherwise leave a
    truncated or interleaved, unparseable JSON file on disk. Path.replace()
    (unlike os.rename(), which refuses to overwrite an existing file on
    Windows) is documented as atomic on both POSIX and Windows, as long as
    source and destination are on the same filesystem -- guaranteed here
    since the temp file is always a sibling of the real one. Shared by
    every profile/settings writer in this app (profiles_store.py and
    app_state.py); the uuid4 suffix (not just the pid) means two threads in
    this same process writing the same path at once still get distinct temp
    files, so neither one's write can stomp the other's temp file, even
    though only one write ultimately wins the final rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    try:
        tmp_path.write_text(text, encoding=encoding)
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


# A real profile_id is always produced by profile_id_from_name() (below),
# which runs safe_filename() and lowercases it -- so it can only ever
# contain these characters, and can never contain "/" or start with ".".
# Path traversal fix: user_profile_path()/shipped_profile_path() used to
# build a Path directly from whatever string was handed in, with no check
# at all -- delete_profile("../app_settings") resolved straight to the real
# app_settings.json one directory above USER_PROFILES_DIR and unlinked it.
# Rejecting anything that doesn't match this pattern closes that off at the
# one place every profile-path lookup in this module goes through, rather
# than patching each caller individually.
_VALID_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _validated_profile_id(profile_id: str) -> str:
    if not _VALID_PROFILE_ID.match(profile_id or ""):
        raise ValueError(f"Not a valid profile id: {profile_id!r}")
    return profile_id


PROJECT_DIR = Path(__file__).resolve().parent
PROFILES_DIR = PROJECT_DIR / "profiles"


def _app_data_base() -> Path:
    """Per-OS application-data base directory. Mirrors the platform.system()
    dispatch pattern app.py's pick_source_folder_dialog() already uses for
    the same "this varies by OS" reason."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    if system == "Windows":
        return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))


def _user_data_dir() -> Path:
    """Per-OS application-data directory for this app's user-generated files
    -- deliberately outside PROJECT_DIR/PROFILES_DIR, so a software update
    (this app's documented update path is: download a fresh copy, replace
    the old folder) can never delete a profile a user created, no matter how
    the replace is done."""
    return _app_data_base() / "Customizable Transcriber"


def _legacy_user_data_dirs() -> list[Path]:
    """The app's earlier names' app-data directories, newest first
    ("Customizable Transcription", then "Transcription Bot") -- kept only so
    ensure_profiles_dir() can migrate an existing install's saved profiles
    into the current directory name the first time it runs after a rename,
    instead of orphaning them."""
    base = _app_data_base()
    return [base / "Customizable Transcription", base / "Transcription Bot"]


USER_DATA_DIR = _user_data_dir()
# Every profile a user saves/edits through the running app -- Prompt Builder,
# the Transcribe page's editor, or Save Profile -- lands here, never in the
# git-tracked PROFILES_DIR above. PROFILES_DIR still ships rendi-*/
# chiusa-sclafani-* as read-only reference examples; see find_profile_path().
USER_PROFILES_DIR = USER_DATA_DIR / "profiles"


def profile_id_from_name(name: str) -> str:
    return safe_filename(name).lower() or "custom-profile"


def shipped_profile_path(profile_id: str) -> Path:
    """Path a built-in/example profile would have inside the repo's tracked
    profiles/ folder. Read-only at runtime -- nothing the app does while
    running ever writes here; only build_prompt.py and hand-authored commits
    do."""
    return PROFILES_DIR / f"{_validated_profile_id(profile_id)}.json"


def user_profile_path(profile_id: str) -> Path:
    """Path a profile is written to whenever the running app saves or edits
    one -- always USER_PROFILES_DIR (see _user_data_dir()), never the
    git-tracked profiles/ folder."""
    return USER_PROFILES_DIR / f"{_validated_profile_id(profile_id)}.json"


def find_profile_path(profile_id: str) -> Path | None:
    """Where a profile's JSON actually lives, or None if it doesn't exist in
    either location (including if profile_id isn't even a structurally valid
    id -- see _validated_profile_id()). Checks USER_PROFILES_DIR first so a
    user's own edited copy of a shipped profile shadows the original --
    overriding it for this user without ever modifying the tracked file
    underneath."""
    try:
        user_path = user_profile_path(profile_id)
    except ValueError:
        return None
    if user_path.exists():
        return user_path
    shipped_path = shipped_profile_path(profile_id)
    if shipped_path.exists():
        return shipped_path
    return None


def ensure_profiles_dir() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    # One-time migration for an existing install: the app-data directory was
    # renamed from "Transcription Bot" to "Customizable Transcription", then
    # to "Customizable Transcriber". If the new directory doesn't exist yet
    # but an old one does, move the newest one wholesale so already-saved profiles aren't
    # orphaned -- rather than leaving them stranded under the old name where
    # nothing looks for them anymore. Best-effort: on any failure (e.g. a
    # cross-device move on an unusual setup) fall through and just create a
    # fresh empty directory below, same as a brand-new install would get.
    if not USER_DATA_DIR.exists():
        for legacy_dir in _legacy_user_data_dirs():
            if legacy_dir.exists() and legacy_dir != USER_DATA_DIR:
                try:
                    USER_DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
                    legacy_dir.rename(USER_DATA_DIR)
                except OSError:
                    pass
                break
    USER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)


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
    USER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(user_profile_path(profile["id"]), json.dumps(profile, indent=2) + "\n")


def load_custom_profiles() -> list[dict[str, str]]:
    """Loads every profile from both PROFILES_DIR (shipped examples, tracked
    in git) and USER_PROFILES_DIR (this user's own saves, outside the app
    folder -- see _user_data_dir()). When the same id exists in both -- a
    user has edited a shipped profile, which write_profile() always saves to
    USER_PROFILES_DIR rather than overwriting the tracked original -- the
    user's copy wins, so their edit takes effect without ever touching the
    shipped file on disk."""
    ensure_profiles_dir()
    by_id: dict[str, dict[str, str]] = {}
    for directory in (PROFILES_DIR, USER_PROFILES_DIR):
        for path in sorted(directory.glob("*.json")):
            # Defensive: an old settings.json from before this file was
            # retired (it used to track the last-selected profile id) could
            # still be sitting on an existing install's disk -- skip it by
            # name rather than trying to parse it as a profile.
            if path.name == "settings.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            # A file can be syntactically valid JSON (`[]`, `null`, `"x"`, a
            # bare number) without being a profile object at all -- e.g. a
            # partially-migrated or externally-synced file. Skip it the same
            # way an unparseable file above is skipped, rather than passing a
            # non-dict into normalize_profile_sections()'s dict-only `.get()`
            # calls, which would raise AttributeError and take down every
            # profile-dependent page for the sake of one bad file.
            if not isinstance(data, dict):
                continue
            data = normalize_profile_sections(data)
            profile_id = str(data.get("id") or path.stem)
            label = str(data.get("label") or profile_id)
            translation_languages = data.get("translation_languages")
            # pb_answers carries the Prompt Builder questionnaire's structured answers
            # (record type, checkboxes, repeatable rows) for profiles saved from that
            # page -- it's what lets Prompt Builder load a profile back in for editing
            # instead of only ever creating new ones. A profile saved elsewhere (the
            # Transcribe page's free-text editor, or hand-authored JSON like most
            # profiles predating this feature) has no such structure to recover, so
            # this is simply absent for them -- profiles_for_browser() never includes
            # it, so it can't leak into the Transcribe/Test Mode page snapshots.
            pb_answers = data.get("pb_answers")
            by_id[profile_id] = {
                "id": profile_id,
                "label": label,
                "kind": str(data.get("kind", "custom")),
                "role_context": str(data.get("role_context", "")),
                "reference_context": str(data.get("reference_context", "")),
                "output_format": str(data.get("output_format", "")),
                "native_language": str(data.get("native_language", "")),
                "translation_languages": list(translation_languages) if isinstance(translation_languages, list) else [],
                "record_type": str(data.get("record_type", "")),
                "pb_answers": pb_answers if isinstance(pb_answers, dict) else None,
            }
    return [by_id[profile_id] for profile_id in sorted(by_id)]


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
    profiles = load_custom_profiles()
    for profile in profiles:
        if profile["id"] == profile_id:
            profile["kind"] = "custom"
            return profile

    # No hardcoded fallback id here on purpose -- the shipped rendi-* profiles
    # this used to fall back to are gone (retired once the Prompt Builder
    # questionnaire made them obsolete), and any future shipped/user profile
    # could just as easily be renamed or deleted. Falling back to whatever
    # profile happens to exist is more robust than depending on one specific
    # id always being present.
    if profiles:
        return profiles[0]

    raise RuntimeError("No prompt profiles are available.")


def save_custom_profile(
    name: str,
    role_context: str,
    reference_context: str,
    output_format: str,
    replace_existing: bool = False,
    native_language: str = "",
    translation_languages: list[str] | None = None,
    record_type: str = "",
    pb_answers: dict | None = None,
) -> dict[str, str]:
    label = name.strip()
    if not label:
        raise RuntimeError("Enter a name before saving a new custom profile.")
    if not any((role_context, reference_context, output_format)):
        raise RuntimeError("Paste role, reference, or output-format content before saving a new custom profile.")

    with _profile_write_lock:
        profile_id = profile_id_from_name(label)
        if not replace_existing:
            base_id = profile_id
            counter = 2
            while find_profile_path(profile_id) is not None:
                profile_id = f"{base_id}-{counter}"
                counter += 1

        profile = {
            "id": profile_id,
            "label": label,
            "kind": "custom",
            "role_context": role_context,
            "reference_context": reference_context,
            "output_format": output_format,
            # Prompt Builder-only for now -- a profile saved from
            # the Transcribe page's manual free-text editor has neither field set,
            # which is exactly what tells write_docx() to skip the header box.
            "native_language": native_language.strip(),
            "translation_languages": list(translation_languages or []),
            "record_type": record_type.strip(),
        }
        if pb_answers:
            # Structured Prompt Builder questionnaire state -- see load_custom_profiles()
            # for why this is kept separate from the three prose fields above.
            profile["pb_answers"] = pb_answers
        USER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_text(user_profile_path(profile_id), json.dumps(profile, indent=2) + "\n")
        return profile


def update_full_profile(
    profile_id: str,
    label: str,
    role_context: str,
    reference_context: str,
    output_format: str,
    native_language: str = "",
    translation_languages: list[str] | None = None,
    record_type: str = "",
    pb_answers: dict | None = None,
) -> dict[str, str]:
    """Overwrite an existing Prompt Builder-created profile in place, by id.

    Unlike save_custom_profile(), this never picks a new id -- write_profile()
    files by profile["id"], not by label, so changing the label here is safe
    and never orphans the original file. Used by Prompt Builder's "Update
    profile" action once a profile with stored pb_answers has been loaded
    back into the questionnaire; see save_prompt_builder_profile().
    """
    with _profile_write_lock:
        profile = load_profile(profile_id)
        if profile["id"] != profile_id:
            # load_profile() silently falls back to the default profile when the
            # id isn't found -- without this guard a stale edit_profile_id would
            # overwrite the wrong file.
            raise RuntimeError(f'Profile "{profile_id}" no longer exists. Save as a new profile instead.')
        if not any((role_context, reference_context, output_format)):
            raise RuntimeError("Paste role, reference, or output-format content before updating a profile.")

        label = label.strip() or profile["label"]
        profile["label"] = label
        profile["role_context"] = role_context
        profile["reference_context"] = reference_context
        profile["output_format"] = output_format
        profile["native_language"] = native_language.strip()
        profile["translation_languages"] = list(translation_languages or [])
        profile["record_type"] = record_type.strip()
        if pb_answers:
            profile["pb_answers"] = pb_answers
        write_profile(profile)
        return profile


def update_profile(profile_id: str, role_context: str, reference_context: str, output_format: str) -> dict[str, str]:
    with _profile_write_lock:
        profile = load_profile(profile_id)
        if profile["id"] != profile_id:
            # Same guard as update_full_profile() above, for the same reason:
            # load_profile() silently falls back to some other real profile
            # when profile_id isn't found, so without this check a stale/bogus
            # id would overwrite the wrong file instead of failing loudly.
            raise RuntimeError(f'Profile "{profile_id}" no longer exists.')
        profile["role_context"] = role_context
        profile["reference_context"] = reference_context
        profile["output_format"] = output_format
        write_profile(profile)
        return profile


# Import/Export Profiles (Prompt Builder page). The exported file is plain
# JSON with a distinctive double extension (.tbprofile.json) -- the base
# extension is the ordinary, universally-allowed ".json" (not on any mail
# provider's blocked-attachment list, unlike script/executable extensions),
# while the compound name still makes the file self-describing to a human
# and to this app on import. The envelope (format/format_version wrapper)
# lets import reject an unrelated JSON file with a clear error instead of
# silently misreading it as a profile.
PROFILE_EXPORT_FORMAT = "customizable-transcriber-profile"
# Format strings from the app's earlier names ("Customizable Transcription",
# "Transcription Bot"). Only ever checked on import, never written -- keeps a
# .tbprofile.json exported before a rename importable, rather than silently
# breaking a file someone already shared.
PROFILE_EXPORT_FORMATS_LEGACY = ("customizable-transcription-profile", "transcription-bot-profile")
PROFILE_EXPORT_FORMAT_VERSION = 1


def export_profile_payload(profile_id: str) -> tuple[str, bytes]:
    profile = load_profile(profile_id)
    if profile["id"] != profile_id:
        # load_profile() silently falls back to the default profile when the
        # id isn't found -- without this guard exporting a stale/deleted id
        # would silently download a different profile instead of erroring.
        raise RuntimeError("Select a valid profile to export.")
    envelope = {
        "format": PROFILE_EXPORT_FORMAT,
        "format_version": PROFILE_EXPORT_FORMAT_VERSION,
        "app_name": "Customizable Transcriber",
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profile": {
            "label": profile["label"],
            "role_context": profile["role_context"],
            "reference_context": profile["reference_context"],
            "output_format": profile["output_format"],
            "native_language": profile.get("native_language", ""),
            "translation_languages": profile.get("translation_languages", []),
            "record_type": profile.get("record_type", ""),
            "pb_answers": profile.get("pb_answers"),
        },
    }
    body = (json.dumps(envelope, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return f"{profile_id}.tbprofile.json", body


def import_custom_profile(file_text: str) -> dict[str, str]:
    try:
        data = json.loads(file_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("That file isn't a valid profile export (not valid JSON).") from exc

    if isinstance(data, dict) and data.get("format") in (PROFILE_EXPORT_FORMAT, *PROFILE_EXPORT_FORMATS_LEGACY):
        profile_data = data.get("profile")
    else:
        # Tolerate a bare profile JSON too -- e.g. one of this app's own
        # profiles/*.json files forwarded directly, without ever having gone
        # through Export. Same shape either way: a flat dict of profile fields.
        profile_data = data
    if not isinstance(profile_data, dict):
        raise RuntimeError("That file doesn't contain a recognizable Customizable Transcriber profile.")

    label = str(profile_data.get("label", "") or "").strip()
    if not label:
        raise RuntimeError("That file has no profile name to import it under.")

    translation_languages = profile_data.get("translation_languages")
    pb_answers = profile_data.get("pb_answers")

    # replace_existing=False (save_custom_profile()'s default) auto-suffixes
    # the name on a collision rather than overwriting -- an imported file
    # never silently clobbers an existing profile.
    return save_custom_profile(
        label,
        str(profile_data.get("role_context", "") or ""),
        str(profile_data.get("reference_context", "") or ""),
        str(profile_data.get("output_format", "") or ""),
        native_language=str(profile_data.get("native_language", "") or ""),
        translation_languages=list(translation_languages) if isinstance(translation_languages, list) else [],
        record_type=str(profile_data.get("record_type", "") or ""),
        pb_answers=pb_answers if isinstance(pb_answers, dict) else None,
    )


def delete_profile(profile_id: str) -> dict[str, str]:
    # Path-traversal + destructive-fallback fix. This used to call
    # load_profile(profile_id) first -- which, by design, silently falls
    # back to some *other* real profile when profile_id doesn't match one
    # (see load_profile()'s own comment; that's the right behavior for a
    # read/display path with no good hardcoded default). Combined with
    # find_profile_path()/user_profile_path() building a Path with no
    # validation at all, that meant delete_profile("../app_settings")
    # reported a misleading "Deleted profile: <unrelated label>" while
    # actually unlinking the real app_settings.json one directory above
    # USER_PROFILES_DIR. No fallback for a destructive operation: an id that
    # isn't in the real listing is an error, full stop.
    with _profile_write_lock:
        matches = [profile for profile in load_custom_profiles() if profile["id"] == profile_id]
        if not matches:
            raise RuntimeError("Select a valid prompt profile before deleting.")
        profile = matches[0]

        path = find_profile_path(profile_id)
        if path is None:
            raise RuntimeError("Select a valid prompt profile before deleting.")

        # Never delete a shipped example, even by a valid id that happens to
        # collide with one -- only a file actually inside USER_PROFILES_DIR is
        # eligible. Resolved (not string-compared) so a symlink can't escape
        # this check either.
        if not path.resolve().is_relative_to(USER_PROFILES_DIR.resolve()):
            raise RuntimeError("Shipped example profiles can't be deleted.")

        path.unlink()
        return profile


# The two functions below render profile *display* representations (an
# HTML <option> list, a JSON-able dict for the browser-side `profiles`
# object every page embeds) rather than storing anything -- originally kept
# in app.py for exactly that reason. Moved here once pages/*.py (the page-render modules) also
# needed them: they depend on nothing but profiles_with_display_labels()
# and html.escape(), so this avoids an app.py <-> pages circular import
# without duplicating either function.
def profile_options_html(selected_profile: str) -> str:
    placeholder_selected = "selected" if not selected_profile else ""
    options = [f'<option value="" disabled {placeholder_selected}>Select a Profile</option>']
    for profile in profiles_with_display_labels():
        profile_id = html.escape(profile["id"])
        label = html.escape(profile["display_label"])
        selected = "selected" if selected_profile == profile["id"] else ""
        options.append(f'<option value="{profile_id}" {selected}>{label}</option>')
    return "\n".join(options)


def profile_zoom_pages(profile: dict) -> bool:
    """The profile's saved Page zoom default: Prompt Builder's "zoomPages"
    checkbox, stored in pb_answers like every other questionnaire answer, and
    only meaningful for a two-facing-pages layout (the checkbox is hidden for
    any other layout, so a stale checked value there is ignored)."""
    answers = profile.get("pb_answers") or {}
    if not isinstance(answers, dict):
        return False
    fields = answers.get("fields") or {}
    checked = answers.get("checked") or {}
    return fields.get("pageLayout") == "two_facing" and bool(checked.get("zoomPages"))


def profiles_for_browser() -> dict[str, dict[str, object]]:
    return {
        profile["id"]: {
            "id": profile["id"],
            "label": profile.get("display_label", profile["label"]),
            "profile_label": profile["label"],
            "role_context": profile.get("role_context", ""),
            "reference_context": profile.get("reference_context", ""),
            "output_format": profile.get("output_format", ""),
            "zoom_pages": profile_zoom_pages(profile),
        }
        for profile in profiles_with_display_labels()
    }
