from __future__ import annotations

import argparse
from pathlib import Path

from transcription_bot.core import (
    DEFAULT_MODEL,
    TranscriptionConfig,
    count_failures,
    default_output_file,
    run_batch,
)


PROJECT_DIR = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe local archival images with Gemini."
    )
    parser.add_argument("image_folder", help="Folder containing image files.")
    parser.add_argument(
        "-o",
        "--output",
        help="Output Markdown file. Defaults to outputs/transcription-<timestamp>.md.",
    )
    parser.add_argument(
        "--prompt",
        default=str(PROJECT_DIR / "prompt.md"),
        help="System prompt file.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name.")
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between images.",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Process files in reverse alphabetical order.",
    )
    parser.add_argument(
        "--include-thoughts",
        action="store_true",
        help="Request model thoughts when supported by the installed SDK/model.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_file = Path(args.output).expanduser() if args.output else default_output_file(PROJECT_DIR)

    config = TranscriptionConfig(
        image_folder=Path(args.image_folder).expanduser(),
        output_file=output_file,
        prompt_file=Path(args.prompt).expanduser(),
        model=args.model,
        delay_seconds=args.delay,
        reverse_order=args.reverse,
        include_thoughts=args.include_thoughts,
    )
    results = run_batch(config, PROJECT_DIR, progress=print)
    failures = count_failures(results)
    print(f"Processed {len(results)} image(s), {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
