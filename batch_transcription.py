"""Off-Peak Mode: submits a whole Transcribe run to the provider's async
Batch API (Gemini's `client.batches`, Anthropic's `client.messages.batches`)
instead of calling the model once per image in real time the way
`core.py`'s `run_batch()` does. In exchange for giving up live per-image
delivery, both providers bill roughly half the standard per-token rate.

Deliberately its own top-level module, not folded into core.py/run_support.py
-- this is the entire new-capability surface for Off-Peak Mode. A reviewer
can read this one file top to bottom without re-reviewing the already-
reviewed real-time run path those two modules own.

Concurrency model: reuses app_state.state/lock/stop_event exactly as a
real-time run does -- see handlers/transcribe_offpeak.py's run_off_peak()
for the reservation, which mirrors handlers/transcribe_run.py's
run_transcription() line for line. There is no second lock and no second
"is something running" concept here; v1 supports exactly one active
operation (Now or Off-Peak) at a time, so occupying state["running"] for
the whole life of the batch job is correct, not a simplification that
will need undoing later.

Per-item identifiers sent to the provider (Gemini's InlinedRequest.metadata,
Anthropic's Request.custom_id) are plain positional indices ("0", "1", "2",
...), never a filename -- this sidesteps any question of sanitizing a
user-controlled filename into a provider-facing identifier field, since a
positional index has no user-controlled content in it at all. A local list
(built once, in the same source_files() order run_batch() itself would use)
maps index -> filename for matching results back up once the batch
completes.

No job state is ever written to disk -- restarting the app abandons any
in-flight off-peak job (a deliberate v1 scope decision agreed with the
user, not an oversight). Everything here lives in app_state.state for
exactly as long as the process does; see that module's own comment on the
new off_peak/batch_provider/batch_job_id/batch_counts fields.
"""

from __future__ import annotations

import time
from pathlib import Path

import anthropic
from google import genai
from google.genai import types as genai_types

from app_state import lock, state, stop_event
from customizable_transcription.core import (
    FILE_TYPE_MIME,
    USER_INSTRUCTION,
    ImageResult,
    _is_transient_provider_error,
    api_key,
    claude_api_key,
    count_failures,
    display_name,
    humanize_provider_error,
    provider_for_model,
    render_entry,
    sniff_file_type,
    source_files,
    validate_batch_source_file,
)
from run_support import write_docx

# Empirically measured this session against a real archival page scan, at
# Gemini's HIGH media-resolution tier (today's implicit default for a
# real-time call) -- confirmed FLAT regardless of the source image's own
# pixel dimensions, since Gemini normalizes an image's token cost
# server-side before billing (see the plan this feature was built from).
# Applied to every Gemini model, not just the one actually measured
# (gemini-3.1-pro-preview) -- this is a directional/blunt estimate by
# explicit design choice, not a precise per-model figure.
GEMINI_IMAGE_TOKENS_ESTIMATE = 1074

# Anthropic's own documented pricing formula is tokens ≈ (width_px *
# height_px) / 750, with an image above ~1568px on its long edge resized
# down to that before billing. Not measured directly in this app -- no
# Anthropic key was available to verify against when this was built (see
# the plan). Computed here from a typical 4:3 archival photo capped at that
# long-edge limit, aspect ratio preserved (1568 x 1176).
CLAUDE_IMAGE_TOKENS_ESTIMATE = round(1568 * 1176 / 750)

OFF_PEAK_DISCOUNT_DESCRIPTION = "roughly half the standard per-token rate for both input and output"


def estimate_off_peak_savings(image_count: int, page_layout: str, model: str) -> str:
    """A deliberately blunt, directional cost-savings estimate -- no
    maintained per-model $/token pricing table, since that would need to be
    kept in sync with provider pricing pages indefinitely (see the plan).
    Varies with volume (image_count) and page layout (from the profile's
    own pb_answers.fields.pageLayout, read server-side by the caller) and
    names the model implicitly via which of the two token-per-image
    constants above applies."""
    if image_count <= 0:
        return "Select a source folder to see an off-peak cost estimate."
    per_image = (
        CLAUDE_IMAGE_TOKENS_ESTIMATE if provider_for_model(model) == "claude" else GEMINI_IMAGE_TOKENS_ESTIMATE
    )
    total_tokens = image_count * per_image
    if page_layout == "one_page":
        page_note = "each image ≈1 register page, per this profile"
    elif page_layout == "two_facing":
        page_note = "each image ≈2 facing pages, per this profile"
    else:
        page_note = "page layout not specified in this profile"
    return (
        f"≈{image_count:,} image(s) found ({page_note}) → roughly {total_tokens:,} image tokens at "
        f"your selected model's standard detail level. Off-peak batch processing is typically billed "
        f"at {OFF_PEAK_DISCOUNT_DESCRIPTION}."
    )

# How often the background thread polls the provider for status while a
# batch is in flight. Aggregate-only progress (succeeded/failed/incomplete
# counts), not per-image -- neither provider's batch status API exposes
# which specific item just finished, only running totals (see the plan's
# own note on this). Short enough that Stop -- which this loop notices
# cooperatively, the same way run_batch() checks cancel_requested() between
# images -- takes effect promptly; long enough not to hammer either
# provider's status endpoint over what could be a multi-hour job.
POLL_INTERVAL_SECONDS = 30

# A poll only *checks* the job's status -- it doesn't touch the job itself,
# so a transient failure here (a 503 while Google/Anthropic's status
# endpoint is momentarily overloaded, a network blip) says nothing about
# whether the actual batch job is healthy. Confirmed the hard way: an
# overnight run's job reached JOB_STATE_SUCCEEDED hours after this loop had
# already aborted on a single failed poll and reported the whole run as a
# fatal error, with no way left to reconnect to it (see the module
# docstring's "no job state on disk" note -- v1 has no persisted job id to
# recover from once this function returns). Tolerating a bounded run of
# consecutive transient poll failures before giving up avoids throwing away
# an otherwise-healthy multi-hour job over one bad status check, while still
# surfacing a real, sustained outage rather than polling silently forever.
# 20 x POLL_INTERVAL_SECONDS(30s) = 10 minutes of continuous transient
# failures tolerated -- generous relative to the blips this is meant to
# absorb, short relative to a run that can span many hours.
MAX_CONSECUTIVE_POLL_FAILURES = 20


class BatchSubmissionError(RuntimeError):
    """Raised when building/validating/submitting the batch itself fails --
    before any per-image outcome exists, so this always aborts the whole
    job (same as run_batch()'s very first image failing) rather than being
    recorded as one failed image among many, unlike a single image's own
    transcription failing inside an otherwise-successful batch, which is
    recorded in the per-image results instead."""


def validated_images(image_folder: Path, extensions) -> list[Path]:
    """Same discovery + per-file validation run_batch() already applies to
    every image before sending it anywhere -- reused here rather than
    duplicated, so a batch job gets identical symlink/size/type protection
    to a real-time run, not a parallel and potentially weaker check."""
    files = source_files(image_folder, extensions)
    for path in files:
        validate_batch_source_file(path, image_folder)
    return files


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def submit_gemini_batch(
    client: genai.Client, model: str, system_prompt: str, images: list[Path]
) -> str:
    requests = []
    for index, path in enumerate(images):
        data = path.read_bytes()
        detected = sniff_file_type(data)
        if detected is None:
            raise BatchSubmissionError(
                f"{path.name} does not look like a JPEG, PNG, or PDF file (checked its content, "
                "not just its extension) -- aborting before submission."
            )
        requests.append(
            genai_types.InlinedRequest(
                model=model,
                contents=[
                    genai_types.Part.from_bytes(data=data, mime_type=FILE_TYPE_MIME[detected]),
                    USER_INSTRUCTION,
                ],
                config=genai_types.GenerateContentConfig(system_instruction=system_prompt, temperature=0),
                metadata={"index": str(index)},
            )
        )
    job = client.batches.create(
        model=model,
        src=requests,
        config=genai_types.CreateBatchJobConfig(display_name="customizable-transcription-offpeak"),
    )
    return job.name


_GEMINI_TERMINAL_STATES = frozenset(
    {
        genai_types.JobState.JOB_STATE_SUCCEEDED,
        genai_types.JobState.JOB_STATE_FAILED,
        genai_types.JobState.JOB_STATE_CANCELLED,
        genai_types.JobState.JOB_STATE_PARTIALLY_SUCCEEDED,
        genai_types.JobState.JOB_STATE_EXPIRED,
    }
)


def poll_gemini_batch(client: genai.Client, job_name: str):
    """Returns the raw BatchJob -- callers read .state/.completion_stats/.dest
    themselves; kept as one raw object rather than a bespoke tuple so
    collect_gemini_batch_results() can reuse the same fetch's .dest without a
    second round trip."""
    return client.batches.get(name=job_name)


def gemini_batch_is_terminal(job) -> bool:
    return job.state in _GEMINI_TERMINAL_STATES


def gemini_batch_counts(job) -> dict[str, int]:
    stats = job.completion_stats
    if stats is None:
        return {}
    return {
        "succeeded": int(stats.successful_count or 0),
        "failed": int(stats.failed_count or 0),
        "incomplete": int(stats.incomplete_count or 0),
    }


def cancel_gemini_batch(client: genai.Client, job_name: str) -> None:
    # Best-effort: the job may already have reached a terminal state on the
    # provider's side by the time Stop is noticed, in which case cancel()
    # itself errors -- that's not a failure worth surfacing, since the
    # outcome (job no longer running) is the same either way.
    try:
        client.batches.cancel(name=job_name)
    except Exception:
        pass


def collect_gemini_batch_results(job) -> dict[int, tuple[str, str]]:
    """index -> (text, error_message). error_message is "" on success."""
    results: dict[int, tuple[str, str]] = {}
    responses = (job.dest.inlined_responses if job.dest else None) or []
    for item in responses:
        meta = item.metadata or {}
        try:
            index = int(meta.get("index", ""))
        except ValueError:
            continue
        if item.error:
            results[index] = ("", item.error.message or str(item.error))
        else:
            text = (item.response.text if item.response else "") or ""
            results[index] = (text, "")
    return results


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

def submit_claude_batch(
    client: anthropic.Anthropic, model: str, system_prompt: str, images: list[Path]
) -> str:
    import base64

    requests = []
    for index, path in enumerate(images):
        data = path.read_bytes()
        detected = sniff_file_type(data)
        if detected is None:
            raise BatchSubmissionError(
                f"{path.name} does not look like a JPEG, PNG, or PDF file (checked its content, "
                "not just its extension) -- aborting before submission."
            )
        mime_type = FILE_TYPE_MIME[detected]
        encoded = base64.standard_b64encode(data).decode("utf-8")
        block_type = "document" if mime_type == "application/pdf" else "image"
        source_block = {
            "type": block_type,
            "source": {"type": "base64", "media_type": mime_type, "data": encoded},
        }
        requests.append(
            {
                "custom_id": str(index),
                "params": {
                    "model": model,
                    "max_tokens": 64000,
                    "output_config": {"effort": "high"},
                    "system": system_prompt,
                    "messages": [
                        {
                            "role": "user",
                            "content": [source_block, {"type": "text", "text": USER_INSTRUCTION}],
                        }
                    ],
                },
            }
        )
    batch = client.messages.batches.create(requests=requests)
    return batch.id


def poll_claude_batch(client: anthropic.Anthropic, batch_id: str):
    return client.messages.batches.retrieve(batch_id)


def claude_batch_is_terminal(batch) -> bool:
    return batch.processing_status == "ended"


def claude_batch_counts(batch) -> dict[str, int]:
    counts = batch.request_counts
    if counts is None:
        return {}
    return {
        "succeeded": int(counts.succeeded or 0),
        "errored": int(counts.errored or 0),
        "processing": int(counts.processing or 0),
        "canceled": int(counts.canceled or 0),
        "expired": int(counts.expired or 0),
    }


def cancel_claude_batch(client: anthropic.Anthropic, batch_id: str) -> None:
    try:
        client.messages.batches.cancel(batch_id)
    except Exception:
        pass


def collect_claude_batch_results(client: anthropic.Anthropic, batch_id: str) -> dict[int, tuple[str, str]]:
    """index -> (text, error_message). error_message is "" on success."""
    results: dict[int, tuple[str, str]] = {}
    for item in client.messages.batches.results(batch_id):
        try:
            index = int(item.custom_id)
        except ValueError:
            continue
        result = item.result
        if result.type == "succeeded":
            text = "".join(block.text for block in result.message.content if block.type == "text")
            results[index] = (text, "")
        elif result.type == "errored":
            results[index] = ("", str(result.error))
        else:
            # "canceled"/"expired" -- no content was ever produced for this item.
            results[index] = ("", f"Request was {result.type}.")
    return results


# ---------------------------------------------------------------------------
# Provider-agnostic job orchestration
# ---------------------------------------------------------------------------

def run_off_peak_job(
    *,
    project_dir: Path,
    image_folder: Path,
    extensions,
    model: str,
    provider: str,
    system_prompt: str,
    api_key_override: str | None,
    markdown_file: Path,
    docx_file: Path,
    profile: dict[str, object],
) -> None:
    """The off-peak counterpart to run_support.py's run_job() -- same
    responsibility (produce the final .md/.docx and update state on
    completion), different mechanism for getting each image transcribed
    (one provider batch job instead of run_batch()'s synchronous per-image
    loop). Always run on a background thread by the caller (see
    handlers/transcribe_offpeak.py), matching run_job()'s own contract."""
    try:
        images = validated_images(image_folder, extensions)
        if not images:
            raise BatchSubmissionError("No source images were found in the selected folder.")
        names = [display_name(path, image_folder) for path in images]

        if provider == "claude":
            key = (api_key_override or "").strip() or claude_api_key(project_dir)
            client = anthropic.Anthropic(api_key=key)
            job_id = submit_claude_batch(client, model, system_prompt, images)
        else:
            key = (api_key_override or "").strip() or api_key(project_dir)
            client = genai.Client(api_key=key)
            job_id = submit_gemini_batch(client, model, system_prompt, images)

        with lock:
            state["batch_provider"] = provider
            state["batch_job_id"] = job_id
            state["batch_counts"] = {"total": len(images)}
            state["log"].append(
                f"Off-peak batch submitted ({len(images)} image(s), job {job_id}). "
                "Processed on the provider's own schedule -- this may take a while."
            )
            state["log"] = state["log"][-300:]

        cancelled = False
        job = None
        consecutive_poll_failures = 0
        while True:
            if stop_event.is_set():
                cancelled = True
                if provider == "claude":
                    cancel_claude_batch(client, job_id)
                else:
                    cancel_gemini_batch(client, job_id)
                with lock:
                    state["log"].append("Off-peak batch cancellation requested.")
                    state["log"] = state["log"][-300:]

            try:
                if provider == "claude":
                    job = poll_claude_batch(client, job_id)
                    terminal = claude_batch_is_terminal(job)
                    counts = claude_batch_counts(job)
                else:
                    job = poll_gemini_batch(client, job_id)
                    terminal = gemini_batch_is_terminal(job)
                    counts = gemini_batch_counts(job)
            except Exception as exc:
                if cancelled:
                    # Stop was already requested and cancel_*_batch() above is
                    # already best-effort -- a poll failure at this point isn't
                    # worth reporting as a fatal error, just stop watching.
                    break
                if not _is_transient_provider_error(exc):
                    raise
                consecutive_poll_failures += 1
                if consecutive_poll_failures > MAX_CONSECUTIVE_POLL_FAILURES:
                    minutes = consecutive_poll_failures * POLL_INTERVAL_SECONDS // 60
                    raise RuntimeError(
                        f"Couldn't check your off-peak batch job's status for about {minutes} minutes "
                        f"({consecutive_poll_failures} consecutive temporary provider errors) -- "
                        f"giving up on watching it. This does NOT necessarily mean the job itself "
                        f"failed: a status check failing says nothing about the job, which keeps "
                        f"running on the provider's own servers regardless. Job id: {job_id}. This "
                        "app has no way to reconnect to an already-submitted job, so check the "
                        "provider's own console/dashboard for its outcome. "
                        f"(Last error: {exc})"
                    ) from exc
                with lock:
                    state["log"].append(
                        f"Off-peak status check failed (transient, {consecutive_poll_failures}/"
                        f"{MAX_CONSECUTIVE_POLL_FAILURES}) -- the batch job itself is unaffected; "
                        f"retrying in {POLL_INTERVAL_SECONDS}s. ({exc})"
                    )
                    state["log"] = state["log"][-300:]
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            consecutive_poll_failures = 0
            counts["total"] = len(images)

            with lock:
                state["batch_counts"] = counts
                state["summary"] = "Off-peak: " + ", ".join(f"{k} {v}" for k, v in counts.items())

            if terminal or cancelled:
                break
            time.sleep(POLL_INTERVAL_SECONDS)

        if provider == "claude":
            results = collect_claude_batch_results(client, job_id)
        elif job is not None:
            results = collect_gemini_batch_results(job)
        else:
            # Cancelled before a single poll ever succeeded (the "cancelled,
            # then a poll failure" branch above breaks with job still None)
            # -- nothing to read results from, same as any other empty batch.
            results = {}

        image_results: list[ImageResult] = []
        with markdown_file.open("w", encoding="utf-8") as output:
            output.write(f"# Transcription Output\n\nSource folder: {image_folder}\n")
            for index, name in enumerate(names):
                text, error = results.get(index, ("", "No result was returned for this image."))
                if error:
                    entry_text = f"ERROR: {error}"
                    image_results.append(ImageResult(name, False, entry_text))
                else:
                    entry_text = text
                    image_results.append(ImageResult(name, True, text))
                output.write(render_entry(name, entry_text))

        if markdown_file.exists():
            write_docx(
                docx_file,
                markdown_file.read_text(encoding="utf-8"),
                native_language=str(profile.get("native_language", "")),
                translation_languages=list(profile.get("translation_languages") or []),
                record_type=str(profile.get("record_type", "")),
                model=model,
                profile_label=str(profile.get("label", "")),
            )

        failures = count_failures(image_results)
        with lock:
            if cancelled:
                state["summary"] = f"Off-peak batch cancelled after {len(image_results)} image(s), {failures} failure(s)."
            else:
                state["summary"] = f"Off-peak: processed {len(image_results)} image(s), {failures} failure(s)."
            state["download"] = str(docx_file) if docx_file.exists() else ""
    except Exception as exc:
        message = humanize_provider_error(exc, model)
        with lock:
            state["log"].append(f"Fatal error: {message}")
            state["log"] = state["log"][-300:]
            state["summary"] = f"Fatal error: {message}"
    finally:
        with lock:
            state["running"] = False
            state["off_peak"] = False
