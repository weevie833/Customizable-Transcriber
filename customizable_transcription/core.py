from __future__ import annotations

import base64
import mimetypes
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import anthropic
from google import genai
from google.genai import types


FILE_TYPE_EXTENSIONS = {
    "jpeg": frozenset({".jpg", ".jpeg"}),
    "png": frozenset({".png"}),
    "pdf": frozenset({".pdf"}),
}
SUPPORTED_SOURCE_EXTENSIONS = frozenset(
    extension
    for extensions in FILE_TYPE_EXTENSIONS.values()
    for extension in extensions
)
FILE_TYPE_MIME = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
}
# Leading-byte signatures for detecting a file's real format from its own
# content, independent of whatever extension the browser/OS attached to it.
# Used by Prompt Builder's Preflight Test, which takes a single ad-hoc upload
# rather than a pre-vetted source folder -- see sniff_file_type().
_MAGIC_BYTES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"%PDF-", "pdf"),
)


def sniff_file_type(data: bytes) -> str | None:
    """Detect jpeg/png/pdf from the file's own leading bytes (a FILE_TYPE_EXTENSIONS
    key), or None if it matches none of them. Trusting content over a filename
    extension means a mislabeled or renamed upload is still read correctly --
    or cleanly rejected as unsupported -- rather than silently sent to the AI
    provider tagged with the wrong MIME type."""
    for signature, file_type in _MAGIC_BYTES:
        if data.startswith(signature):
            return file_type
    return None
DEFAULT_MODEL = "gemini-3.1-pro-preview"
USER_INSTRUCTION = "Transcribe and translate this document word-for-word."
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
DATE_FOLDER_PATTERN = re.compile(r"^(\d{4})\s+([A-Za-z]+)\s+(\d{1,2})$")


@dataclass(frozen=True)
class TranscriptionConfig:
    image_folder: Path
    output_file: Path
    prompt_file: Path
    model: str = DEFAULT_MODEL
    delay_seconds: float = 2.0
    reverse_order: bool = False
    include_thoughts: bool = False
    system_prompt: str | None = None
    api_key_override: str | None = None
    source_extensions: frozenset[str] = field(default_factory=lambda: SUPPORTED_SOURCE_EXTENSIONS)


@dataclass(frozen=True)
class ImageResult:
    filename: str
    ok: bool
    text: str


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip("\"'")


def api_key(project_dir: Path) -> str:
    load_env_file(project_dir / ".env")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env or export it before running."
        )
    if key == "your_api_key_here":
        raise RuntimeError("GEMINI_API_KEY is still set to the placeholder value.")
    return key


def claude_api_key(project_dir: Path) -> str:
    load_env_file(project_dir / ".env")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or export it before running."
        )
    if key == "your_api_key_here":
        raise RuntimeError("ANTHROPIC_API_KEY is still set to the placeholder value.")
    return key


def provider_for_model(model: str) -> str:
    return "claude" if model.startswith("claude-") else "gemini"


def key_looks_like_claude(api_key: str) -> bool:
    return api_key.strip().startswith("sk-ant-")


def key_matches_provider(model: str, api_key: str) -> bool:
    """Loose, prefix-based sanity check -- not a substitute for a real API call.

    Anthropic keys reliably start with "sk-ant-", so a Claude model paired
    with a key that doesn't start that way is unambiguously wrong. Gemini/
    Google AI keys don't have one universal prefix, so a Gemini model just
    requires the key to *not* look like an Anthropic one.
    """
    looks_claude = key_looks_like_claude(api_key)
    return looks_claude if provider_for_model(model) == "claude" else not looks_claude


def parse_date_folder(name: str) -> tuple[int, int, int] | None:
    match = DATE_FOLDER_PATTERN.match(name.strip())
    if not match:
        return None

    year = int(match.group(1))
    month = MONTHS.get(match.group(2).lower())
    day = int(match.group(3))
    if not month:
        return None
    return year, month, day


def date_from_path(path: Path, root: Path) -> tuple[int, int, int] | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None

    for part in reversed(relative.parts[:-1]):
        parsed = parse_date_folder(part)
        if parsed:
            return parsed
    return None


_DIGIT_RUN_PATTERN = re.compile(r"(\d+)")


def _natural_sort_key(text: str) -> tuple:
    """Splits text into alternating non-digit/digit chunks so an embedded
    number sorts by its integer value, not as a string. Plain string sorting
    put "Page (24).jpg" before "Page (4).jpg" before "Page (5).jpg" -- '2' < '4'
    < '5' as characters -- so a real folder of Page (4)/(5)/(24)/(32) processed
    in the order 24, 32, 4, 5 instead of 4, 5, 24, 32.

    Every chunk becomes a (type_marker, value) pair -- (0, "page ") for text,
    (1, 24) for a digit run -- rather than a bare int or str. Comparing two
    natural keys compares these pairs position by position; the leading
    int marker (0 or 1) always resolves a type mismatch before Python would
    otherwise try to compare an int chunk against a str chunk directly, which
    raises TypeError. Without this, one filename with a numeric run at a
    position where another filename has a text run (a very plausible mix in
    a real source folder) would crash the whole batch run's file listing
    instead of just sorting oddly.
    """
    return tuple(
        (1, int(chunk)) if chunk.isdigit() else (0, chunk.lower())
        for chunk in _DIGIT_RUN_PATTERN.split(text)
        if chunk
    )


def image_sort_key(path: Path, root: Path) -> tuple[object, ...]:
    relative = path.relative_to(root)
    parsed_date = date_from_path(path, root)
    if parsed_date:
        return (0, parsed_date, _natural_sort_key(str(relative.parent)), _natural_sort_key(path.name))
    return (1, _natural_sort_key(str(relative.parent)), _natural_sort_key(path.name))


def display_name(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def source_files(folder: Path, extensions: Iterable[str], reverse_order: bool = False) -> list[Path]:
    if not folder.exists():
        raise FileNotFoundError(f"Source folder does not exist: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Source folder is not a directory: {folder}")

    allowed_extensions = {extension.lower() for extension in extensions}
    files = sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in allowed_extensions
        ),
        key=lambda path: image_sort_key(path, folder),
    )
    if reverse_order:
        files.reverse()
    return files


def extensions_for_file_type(file_type: str) -> frozenset[str]:
    try:
        return FILE_TYPE_EXTENSIONS[file_type]
    except KeyError as exc:
        raise RuntimeError("Select JPEG, PNG, or PDF as the source file type.") from exc


def count_source_files_by_type(folder: Path) -> dict[str, int]:
    if not folder.exists():
        raise FileNotFoundError(f"Source folder does not exist: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Source folder is not a directory: {folder}")

    counts = {file_type: 0 for file_type in FILE_TYPE_EXTENSIONS}
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        for file_type, extensions in FILE_TYPE_EXTENSIONS.items():
            if suffix in extensions:
                counts[file_type] += 1
                break
    return counts


def default_output_file(project_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return project_dir / "outputs" / f"transcription-{stamp}.md"


@dataclass
class LLMClient:
    provider: str
    gemini: genai.Client | None = None
    claude: anthropic.Anthropic | None = None


def make_client(
    project_dir: Path,
    model: str,
    api_key_override: str | None = None,
    timeout_seconds: float | None = None,
) -> LLMClient:
    # timeout_seconds is None for every existing caller (run_batch(), via the
    # real Transcribe page) -- a real batch run is a long-lived background job
    # with its own per-image progress log, and deliberately gives the provider
    # unlimited patience rather than aborting a slow-but-working image. Only
    # Prompt Builder's Preflight Test (app.py) passes a real value, since that
    # call blocks a single foreground request and a hung connection there has
    # no progress log to fall back on -- see preflight_test_prompt_builder().
    provider = provider_for_model(model)
    if provider == "claude":
        key = (api_key_override or "").strip() or claude_api_key(project_dir)
        claude_kwargs: dict[str, object] = {"api_key": key}
        if timeout_seconds is not None:
            claude_kwargs["timeout"] = timeout_seconds
        return LLMClient(provider="claude", claude=anthropic.Anthropic(**claude_kwargs))
    key = (api_key_override or "").strip() or api_key(project_dir)
    gemini_kwargs: dict[str, object] = {"api_key": key}
    if timeout_seconds is not None:
        gemini_kwargs["http_options"] = types.HttpOptions(timeout=int(timeout_seconds * 1000))
    return LLMClient(provider="gemini", gemini=genai.Client(**gemini_kwargs))


def validate_api_key(project_dir: Path, model: str, api_key_override: str | None = None) -> None:
    client = make_client(project_dir, model, api_key_override)
    if client.provider == "claude":
        client.claude.messages.create(
            model=model,
            max_tokens=4,
            messages=[{"role": "user", "content": "Reply with OK."}],
        )
        return
    client.gemini.models.generate_content(
        model=model,
        contents="Reply with OK.",
        config=types.GenerateContentConfig(max_output_tokens=4),
    )


# A response cut off mid-generation by the provider's own output-token cap is
# worse than an honest [illegible] -- it drops content with no marker at all,
# and (unlike a max_tokens error that aborts the image outright) a genuinely
# large image can have several real entries land after the cutoff, silently
# missing from the DOCX. Keep whatever text did come back -- it's still real,
# usable model output up to that point -- but append a marker that can't be
# missed, matching this app's existing convention of flagging a gap rather
# than hiding it (see the Uncertainty Protocol's [illegible]/[damaged]).
_TRUNCATION_NOTICE = (
    "\n\n[TRUNCATED: this image's response hit the model's output token limit before "
    "finishing. Everything above is genuine model output, but later entries on this image "
    "may be missing entirely. Re-run this image on its own, or raise the output token limit "
    "in customizable_transcription/core.py, to recover the rest.]"
)


def _transcribe_image_gemini(
    client: genai.Client,
    image_path: Path,
    mime_type: str,
    system_prompt: str,
    model: str,
    include_thoughts: bool,
    max_thinking_level: str | None = None,
) -> str:
    config_kwargs = {"system_instruction": system_prompt, "temperature": 0}

    if include_thoughts and hasattr(types, "ThinkingConfig"):
        config_kwargs["thinking_config"] = types.ThinkingConfig(include_thoughts=True)
    elif (
        max_thinking_level
        and model.startswith("gemini-3")
        and hasattr(types, "ThinkingConfig")
        and hasattr(types, "ThinkingLevel")
    ):
        # A real batch run (include_thoughts False, max_thinking_level None)
        # leaves Gemini 3.x's default (uncapped) thinking budget untouched --
        # this only fires for a caller that explicitly asks for a ceiling, e.g.
        # Prompt Builder's Preflight Test, where "high" reasoning over a full
        # image plus a long system prompt can otherwise run for several
        # minutes with no feedback. See call_gemini_json() in
        # xls_conversion/ai_parser.py for the same cap on its own calls.
        level = getattr(types.ThinkingLevel, max_thinking_level, None)
        if level is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level)

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_path.read_bytes(), mime_type=mime_type),
            USER_INSTRUCTION,
        ],
        config=types.GenerateContentConfig(**config_kwargs),
    )
    text = response.text or ""
    candidates = getattr(response, "candidates", None) or []
    if candidates and getattr(candidates[0], "finish_reason", None) == types.FinishReason.MAX_TOKENS:
        text += _TRUNCATION_NOTICE
    return text


def _transcribe_image_claude(
    client: anthropic.Anthropic,
    image_path: Path,
    mime_type: str,
    system_prompt: str,
    model: str,
) -> str:
    data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    block_type = "document" if mime_type == "application/pdf" else "image"
    source_block = {
        "type": block_type,
        "source": {"type": "base64", "media_type": mime_type, "data": data},
    }
    # Streaming, not a plain (non-streaming) messages.create() call. This used
    # to be non-streaming with max_tokens capped at 16000 -- raised once
    # already from 8192 after truncating mid-entry, with a comment noting
    # 16000 was "the documented safe ceiling for a non-streaming call; going
    # higher risks the SDK's own HTTP timeout." That ceiling was hit for real:
    # a dense marriage-register image (several entries, each with a full
    # native transcription, translation, and notes) still exceeded 16000 and
    # got cut off mid-entry. Per Anthropic's own SDK guidance, a non-streaming
    # request is capped near 16000 specifically to stay under the SDK's HTTP
    # timeout -- streaming removes that constraint entirely, which is why
    # max_tokens can now go to 64000 instead of trying to guess a higher safe
    # non-streaming number.
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        # This SDK's Messages API has no temperature knob (Gemini's temperature=0
        # equivalent doesn't exist here) -- "high" effort is the closest available
        # lever for careful, consistent transcription output.
        output_config={"effort": "high"},
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [source_block, {"type": "text", "text": USER_INSTRUCTION}],
            }
        ],
    ) as stream:
        response = stream.get_final_message()
    text = "".join(block.text for block in response.content if block.type == "text")
    if response.stop_reason == "max_tokens":
        text += _TRUNCATION_NOTICE
    return text


def transcribe_image(
    client: LLMClient,
    image_path: Path,
    system_prompt: str,
    model: str,
    include_thoughts: bool = False,
    max_thinking_level: str | None = None,
) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    if client.provider == "claude":
        return _transcribe_image_claude(client.claude, image_path, mime_type, system_prompt, model)
    return _transcribe_image_gemini(
        client.gemini, image_path, mime_type, system_prompt, model, include_thoughts, max_thinking_level
    )


def collapse_source_line_breaks(text: str) -> str:
    paragraphs: list[str] = []
    current: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue

        if line.endswith(":") and current:
            paragraphs.append(" ".join(current))
            current = [line]
            continue

        current.append(line)

    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs)


def strip_model_record_headers(text: str) -> str:
    lines = text.splitlines()
    while lines and re.match(r"^\s*-{3,}\s*START OF RECORD:.*-{3,}\s*$", lines[0], re.IGNORECASE):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines)


def render_entry(filename: str, text: str) -> str:
    clean_text = collapse_source_line_breaks(strip_model_record_headers(text))
    return f"\n\n--- START OF RECORD: {filename} ---\n\n{clean_text}\n"


def run_batch(
    config: TranscriptionConfig,
    project_dir: Path,
    progress: Callable[[str], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> list[ImageResult]:
    prompt = config.system_prompt or config.prompt_file.read_text(encoding="utf-8")
    files = source_files(config.image_folder, config.source_extensions, config.reverse_order)
    config.output_file.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        if progress:
            progress(message)

    log(f"Found {len(files)} source file(s).")
    client = make_client(project_dir, config.model, config.api_key_override)
    results: list[ImageResult] = []

    with config.output_file.open("w", encoding="utf-8") as output:
        output.write(f"# Transcription Output\n\nSource folder: {config.image_folder}\n")

        for index, image_path in enumerate(files, start=1):
            if cancel_requested and cancel_requested():
                log("Stopped before next image.")
                break

            name = display_name(image_path, config.image_folder)
            log(f"[{index}/{len(files)}] Processing {name}")
            try:
                text = transcribe_image(
                    client=client,
                    image_path=image_path,
                    system_prompt=prompt,
                    model=config.model,
                    include_thoughts=config.include_thoughts,
                )
                output.write(render_entry(name, text))
                output.flush()
                results.append(ImageResult(name, True, text))
                log(f"Saved {name}")
            except Exception as exc:
                error = f"ERROR: {exc}"
                output.write(render_entry(name, error))
                output.flush()
                results.append(ImageResult(name, False, error))
                log(f"Failed {name}: {exc}")

            if config.delay_seconds > 0 and index < len(files):
                remaining_delay = config.delay_seconds
                while remaining_delay > 0:
                    if cancel_requested and cancel_requested():
                        log("Stopped during delay before next image.")
                        break
                    sleep_time = min(0.25, remaining_delay)
                    time.sleep(sleep_time)
                    remaining_delay -= sleep_time
                if cancel_requested and cancel_requested():
                    break

    if cancel_requested and cancel_requested():
        log(f"Stopped. Partial output: {config.output_file}")
    else:
        log(f"Done. Output: {config.output_file}")
    return results


def count_failures(results: Iterable[ImageResult]) -> int:
    return sum(1 for result in results if not result.ok)
