from __future__ import annotations

import mimetypes
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

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
IMAGE_EXTENSIONS = SUPPORTED_SOURCE_EXTENSIONS
DEFAULT_MODEL = "gemini-3.5-flash-lite"
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


def image_sort_key(path: Path, root: Path) -> tuple[object, ...]:
    relative = path.relative_to(root)
    parsed_date = date_from_path(path, root)
    if parsed_date:
        return (0, parsed_date, str(relative.parent).lower(), path.name.lower())
    return (1, str(relative.parent).lower(), path.name.lower())


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


def image_files(folder: Path, reverse_order: bool = False) -> list[Path]:
    return source_files(folder, IMAGE_EXTENSIONS, reverse_order)


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


def make_client(project_dir: Path, api_key_override: str | None = None) -> genai.Client:
    key = (api_key_override or "").strip() or api_key(project_dir)
    return genai.Client(api_key=key)




def validate_api_key(project_dir: Path, model: str, api_key_override: str | None = None) -> None:
    client = make_client(project_dir, api_key_override)
    client.models.generate_content(
        model=model,
        contents="Reply with OK.",
        config=types.GenerateContentConfig(max_output_tokens=4),
    )

def transcribe_image(
    client: genai.Client,
    image_path: Path,
    system_prompt: str,
    model: str,
    include_thoughts: bool = False,
) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    config_kwargs = {"system_instruction": system_prompt}

    if include_thoughts and hasattr(types, "ThinkingConfig"):
        config_kwargs["thinking_config"] = types.ThinkingConfig(include_thoughts=True)

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_path.read_bytes(), mime_type=mime_type),
            USER_INSTRUCTION,
        ],
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return response.text or ""


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
    client = make_client(project_dir, config.api_key_override)
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
