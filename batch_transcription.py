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

Everything here lives in app_state.state for exactly as long as the process
does -- see that module's own comment on the off_peak/batch_provider/
batch_job_id/batch_counts fields -- EXCEPT the small amount of non-secret
job metadata (provider, model, job id, submission time, status) mirrored to
app_state.OFF_PEAK_JOB_FILE at each stage of a job's lifecycle. That was a
deliberate v1 scope decision to write nothing at all (see CODEX_REVIEW.md
finding H-1 / HUMAN_DECISIONS.md HD-1 for why it was revisited): a batch job
can run for hours, and a Stop request that the provider never actually
confirmed -- or an app restart/crash mid-batch -- used to leave no trace
anywhere that a real, possibly still-running (and still billing) provider
job existed. The API key itself is never written to this file, or anywhere
else this app persists to disk.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import anthropic
import httpx
from google import genai
from google.genai import types as genai_types

from app_state import (
    clear_off_peak_job_state,
    lock,
    state,
    stop_event,
    write_off_peak_job_state,
)
from customizable_transcription.core import (
    BATCH_REQUEST_TIMEOUT_SECONDS,
    FILE_TYPE_MIME,
    USER_INSTRUCTION,
    ImageResult,
    _is_transient_provider_error,
    api_key,
    claude_api_key,
    count_failures,
    display_name,
    humanize_provider_error,
    physical_neighbors,
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
# fatal error. The job id is now persisted (see app_state.OFF_PEAK_JOB_FILE)
# so it survives that failure for manual provider-console recovery, but this
# app still has no way to *reconnect and keep watching* it automatically --
# see the module docstring. Tolerating a bounded run of consecutive
# transient poll failures before giving up avoids throwing away an
# otherwise-healthy multi-hour job over one bad status check, while still
# surfacing a real, sustained outage rather than polling silently forever.
# 20 x POLL_INTERVAL_SECONDS(30s) = 10 minutes of continuous transient
# failures tolerated -- generous relative to the blips this is meant to
# absorb, short relative to a run that can span many hours. Deliberately the
# same duration as CANCELLATION_CONFIRMATION_TIMEOUT_SECONDS below -- both
# are "how long is it reasonable to keep trying before telling the user we
# genuinely don't know" bounds, just triggered by different conditions (a
# run of failures here; simply never reaching a terminal state there).
MAX_CONSECUTIVE_POLL_FAILURES = 20

# How long to keep polling after Stop is pressed before giving up on
# confirmation and reporting the cancellation as unconfirmed rather than
# claiming success -- see CODEX_REVIEW.md finding H-1 / HUMAN_DECISIONS.md
# HD-1. Before this, the poll loop broke out the instant `cancelled` was
# set, regardless of whether the very next status check (or even a FAILED
# status check) actually confirmed the provider had stopped the job -- a
# false "cancelled" could be reported while the job kept running, and
# possibly billing, on the provider's own servers.
CANCELLATION_CONFIRMATION_TIMEOUT_SECONDS = 600

# Explicit, bounded timeouts for every provider call this module makes --
# see CODEX_REVIEW.md finding M-3 / HUMAN_DECISIONS.md. Before this, both
# SDK clients were constructed with no timeout at all, so a network stall
# during submission, polling, cancellation, or result retrieval could hang
# indefinitely (the SDK's own default, if any, was never a deliberate choice
# this app made). Two tiers, not one uniform value:
#
# - Submission (uploads every image's full bytes in one request) and result
#   collection (downloads every response) are genuinely heavy transfers --
#   they get the same generous bound run_batch()'s own real-time per-image
#   calls already use (BATCH_REQUEST_TIMEOUT_SECONDS).
# - Status polling and cancellation are small, fixed-size requests. A much
#   shorter bound catches a hung connection quickly instead of waiting up to
#   10 minutes for what should be a sub-second round trip, and keeps Stop
#   (which this loop only checks between polls) responsive. Comfortably
#   above POLL_INTERVAL_SECONDS so a normal poll is never mistaken for a
#   timeout.
BATCH_SUBMIT_TIMEOUT_SECONDS = BATCH_REQUEST_TIMEOUT_SECONDS
BATCH_STATUS_TIMEOUT_SECONDS = 60


def _gemini_client(key: str, timeout_seconds: float) -> genai.Client:
    return genai.Client(
        api_key=key, http_options=genai_types.HttpOptions(timeout=int(timeout_seconds * 1000))
    )


def _claude_client(key: str, timeout_seconds: float) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=key, timeout=timeout_seconds)


def _is_transient_poll_error(exc: Exception) -> bool:
    """_is_transient_provider_error() plus a network-level timeout. Gemini's
    SDK lets httpx.TimeoutException propagate raw rather than wrapping it in
    its own error type (confirmed: xls_conversion/ai_parser.py and
    handlers/profiles.py already catch httpx.TimeoutException directly for
    the same reason), so relying on _is_transient_provider_error() alone
    here would treat a single Gemini status-check timeout as fatal while an
    equivalent Claude timeout -- wrapped in anthropic.APITimeoutError, a
    subclass of APIConnectionError -- already gets this loop's normal
    bounded retry-and-backoff treatment. A timed-out status *check* says
    nothing about the batch job itself, same reasoning as every other
    transient error this loop already tolerates."""
    return _is_transient_provider_error(exc) or isinstance(exc, httpx.TimeoutException)


def _log_timestamp() -> str:
    """A run_batch()-style per-image log line is self-explanatory on its
    own ("[3/10] Processing x.jpg") because the next line follows within
    seconds. An off-peak job's log lines can be hours apart with nothing in
    between, so unlike core.py's real-time log() calls, these are worth a
    wall-clock timestamp -- otherwise "batch submitted" and "batch
    completed" read as if they happened back to back."""
    return datetime.now().strftime("%H:%M:%S")


class BatchSubmissionError(RuntimeError):
    """Raised when building/validating/submitting the batch itself fails --
    before any per-image outcome exists, so this always aborts the whole
    job (same as run_batch()'s very first image failing) rather than being
    recorded as one failed image among many, unlike a single image's own
    transcription failing inside an otherwise-successful batch, which is
    recorded in the per-image results instead."""


# Aggregate batch-capacity caps -- see CODEX_REVIEW.md finding M-2 /
# HUMAN_DECISIONS.md HD-2. MAX_BATCH_IMAGE_BYTES (core.py) already bounds
# any *one* source file, but nothing bounded the batch as a whole: Gemini's
# submit_gemini_batch() keeps every image's raw bytes in one in-memory
# request list, and Claude's submit_claude_batch() additionally base64-
# encodes each one (~1.33x expansion) and keeps that expanded string too --
# a folder of many individually-valid files could still exhaust host memory
# before a single byte ever reaches the provider. Both caps are enforced by
# validated_images() below, before any file's contents are read (a
# Path.stat() call reads only metadata) -- a batch that exceeds either is
# rejected outright with a clear count/size, same as a single oversized file
# already is.
#
# These are directional defaults, not measured against this app's own real
# workloads -- reasonable starting points for a local single-user tool with
# a typical consumer-machine memory budget (a few GB free), not a precise
# capacity plan. Worth revisiting with real numbers (largest legitimate
# batch size, minimum target host memory) if they turn out to be too tight
# or too loose in practice.
MAX_BATCH_IMAGE_COUNT = 1000
# Expressed as a raw-bytes ceiling on the SUM of every source file's own
# size -- Claude's base64 expansion (~1.33x) on top of this is accepted as
# the cost of using that provider, not built into the number itself, so
# both providers are held to the same real "how many original-file bytes
# can this batch contain" limit.
MAX_BATCH_AGGREGATE_BYTES = 2_000_000_000  # ~2GB of combined raw source-file bytes


def validated_images(image_folder: Path, extensions, reverse_order: bool = False) -> list[Path]:
    """Same discovery + per-file validation run_batch() already applies to
    every image before sending it anywhere -- reused here rather than
    duplicated, so a batch job gets identical symlink/size/type protection
    to a real-time run, not a parallel and potentially weaker check.
    reverse_order threads through to source_files() the same "newest first"
    switch the real-time /run path already honors -- see CODEX_REVIEW.md
    finding M-1 / run_off_peak_job()'s own reverse_order parameter.

    Also enforces MAX_BATCH_IMAGE_COUNT/MAX_BATCH_AGGREGATE_BYTES (M-2,
    above) -- item count is checked first, cheaply, before touching the
    filesystem at all; the aggregate-byte running total is accumulated
    alongside the existing per-file validate_batch_source_file() calls
    (which already stat() every file) rather than statting each file twice."""
    files = source_files(image_folder, extensions, reverse_order=reverse_order)
    if len(files) > MAX_BATCH_IMAGE_COUNT:
        raise BatchSubmissionError(
            f"This folder has {len(files):,} source image(s), over the {MAX_BATCH_IMAGE_COUNT:,}-image "
            "limit for a single off-peak batch. Split it into smaller batches (e.g. by sub-folder or "
            "date range) and run each one separately."
        )
    total_bytes = 0
    for path in files:
        validate_batch_source_file(path, image_folder)
        total_bytes += path.stat().st_size
        if total_bytes > MAX_BATCH_AGGREGATE_BYTES:
            raise BatchSubmissionError(
                f"This folder's source images total over {MAX_BATCH_AGGREGATE_BYTES / 1_000_000:,.0f} MB "
                "combined, over the aggregate limit for a single off-peak batch. Split it into smaller "
                "batches (e.g. by sub-folder or date range) and run each one separately."
            )
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

def _batch_was_cancelled(provider: str, job) -> bool:
    """Whether a job's own terminal state actually reflects cancellation --
    not just that Stop was pressed at some point during the run. The
    provider can finish a job's remaining items before a cancel request
    takes effect, which is a legitimate "it just finished anyway" outcome,
    not a cancellation, and deserves an honest message rather than a
    blanket "cancelled" label regardless of what actually happened. See
    CODEX_REVIEW.md finding H-1."""
    if provider == "claude":
        return bool(claude_batch_counts(job).get("canceled"))
    return job.state == genai_types.JobState.JOB_STATE_CANCELLED


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
    reverse_order: bool = False,
) -> None:
    """The off-peak counterpart to run_support.py's run_job() -- same
    responsibility (produce the final .md/.docx and update state on
    completion), different mechanism for getting each image transcribed
    (one provider batch job instead of run_batch()'s synchronous per-image
    loop). Always run on a background thread by the caller (see
    handlers/transcribe_offpeak.py), matching run_job()'s own contract.
    reverse_order mirrors run_job()'s own TranscriptionConfig.reverse_order --
    see CODEX_REVIEW.md finding M-1: the confirmation UI promises a
    newest-to-oldest run will honor that order, so the submitted batch's
    request order (and therefore the output's entry order) must match it."""
    job_id: str | None = None
    submitted_at_iso = ""
    try:
        images = validated_images(image_folder, extensions, reverse_order=reverse_order)
        if not images:
            raise BatchSubmissionError("No source images were found in the selected folder.")
        names = [display_name(path, image_folder) for path in images]

        if provider == "claude":
            key = (api_key_override or "").strip() or claude_api_key(project_dir)
            heavy_client = _claude_client(key, BATCH_SUBMIT_TIMEOUT_SECONDS)
            light_client = _claude_client(key, BATCH_STATUS_TIMEOUT_SECONDS)
        else:
            key = (api_key_override or "").strip() or api_key(project_dir)
            heavy_client = _gemini_client(key, BATCH_SUBMIT_TIMEOUT_SECONDS)
            light_client = _gemini_client(key, BATCH_STATUS_TIMEOUT_SECONDS)

        submit_started = time.monotonic()
        try:
            if provider == "claude":
                job_id = submit_claude_batch(heavy_client, model, system_prompt, images)
            else:
                job_id = submit_gemini_batch(heavy_client, model, system_prompt, images)
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - submit_started
            raise BatchSubmissionError(
                f"Submitting the off-peak batch ({len(images)} image(s)) did not finish within "
                f"{BATCH_SUBMIT_TIMEOUT_SECONDS}s (waited {elapsed:.0f}s) -- the connection stalled "
                "while uploading. Try again, or with a smaller batch."
            ) from exc

        submitted_at_iso = datetime.now().isoformat(timespec="seconds")
        write_off_peak_job_state(
            provider=provider, model=model, job_id=job_id,
            submitted_at=submitted_at_iso, status="running",
        )
        with lock:
            state["batch_provider"] = provider
            state["batch_job_id"] = job_id
            state["batch_counts"] = {"total": len(images)}
            state["log"].append(
                f"[{_log_timestamp()}] Off-peak batch submitted ({len(images)} image(s), job {job_id}). "
                "Processed on the provider's own schedule -- this may take a while."
            )
            state["log"] = state["log"][-300:]

        cancelled = False
        cancel_requested_at: float | None = None
        cancellation_unconfirmed = False
        job = None
        consecutive_poll_failures = 0
        last_logged_counts: dict[str, int] | None = None
        while True:
            if stop_event.is_set():
                if not cancelled:
                    cancelled = True
                    cancel_requested_at = time.monotonic()
                    write_off_peak_job_state(
                        provider=provider, model=model, job_id=job_id,
                        submitted_at=submitted_at_iso, status="cancellation_requested",
                    )
                    with lock:
                        state["log"].append(
                            f"[{_log_timestamp()}] Off-peak batch cancellation requested -- waiting "
                            "for the provider to confirm before reporting an outcome."
                        )
                        state["log"] = state["log"][-300:]
                if provider == "claude":
                    cancel_claude_batch(light_client, job_id)
                else:
                    cancel_gemini_batch(light_client, job_id)

            try:
                if provider == "claude":
                    job = poll_claude_batch(light_client, job_id)
                    terminal = claude_batch_is_terminal(job)
                    counts = claude_batch_counts(job)
                else:
                    job = poll_gemini_batch(light_client, job_id)
                    terminal = gemini_batch_is_terminal(job)
                    counts = gemini_batch_counts(job)
            except Exception as exc:
                # Deliberately no "if cancelled: treat this as done" shortcut
                # here (there used to be one) -- see CODEX_REVIEW.md finding
                # H-1: a poll failure right after Stop says nothing about
                # whether the provider actually stopped the job, so it goes
                # through the exact same bounded transient-retry treatment as
                # any other poll failure. The cancellation-confirmation
                # deadline below (checked after a *successful* poll) is what
                # eventually gives up on a cancellation that truly never
                # confirms; this path gives up (the same way an uncancelled
                # run already does) only after sustained, repeated failures.
                if not _is_transient_poll_error(exc):
                    raise
                consecutive_poll_failures += 1
                if consecutive_poll_failures > MAX_CONSECUTIVE_POLL_FAILURES:
                    minutes = consecutive_poll_failures * POLL_INTERVAL_SECONDS // 60
                    cancel_note = (
                        " You requested cancellation, but this app was never able to confirm it took "
                        "effect."
                        if cancelled
                        else ""
                    )
                    raise RuntimeError(
                        f"Couldn't check your off-peak batch job's status for about {minutes} minutes "
                        f"({consecutive_poll_failures} consecutive temporary provider errors) -- "
                        f"giving up on watching it.{cancel_note} This does NOT necessarily mean the "
                        f"job itself failed: a status check failing says nothing about the job, which "
                        f"keeps running on the provider's own servers regardless. Job id: {job_id}. "
                        "This app has no way to reconnect to an already-submitted job, so check the "
                        "provider's own console/dashboard for its outcome. "
                        f"(Last error: {exc})"
                    ) from exc
                with lock:
                    state["log"].append(
                        f"[{_log_timestamp()}] Off-peak status check failed (transient, "
                        f"{consecutive_poll_failures}/{MAX_CONSECUTIVE_POLL_FAILURES}) -- the batch "
                        f"job itself is unaffected; retrying in {POLL_INTERVAL_SECONDS}s. ({exc})"
                    )
                    state["log"] = state["log"][-300:]
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            consecutive_poll_failures = 0
            counts["total"] = len(images)

            with lock:
                state["batch_counts"] = counts
                state["summary"] = "Off-peak: " + ", ".join(f"{k} {v}" for k, v in counts.items())
                # Log a line only when the counts actually change, not on
                # every 30-second poll -- a multi-hour job would otherwise
                # bury the console in hundreds of identical "no change"
                # lines. Compared against a copy with "total" removed since
                # that key never changes and would never let this fire on
                # its own.
                comparable_counts = {k: v for k, v in counts.items() if k != "total"}
                if comparable_counts != last_logged_counts:
                    state["log"].append(
                        f"[{_log_timestamp()}] Off-peak progress: "
                        + ", ".join(f"{k} {v}" for k, v in counts.items())
                    )
                    state["log"] = state["log"][-300:]
                    last_logged_counts = comparable_counts

            if terminal:
                break
            if (
                cancelled
                and cancel_requested_at is not None
                and time.monotonic() - cancel_requested_at > CANCELLATION_CONFIRMATION_TIMEOUT_SECONDS
            ):
                cancellation_unconfirmed = True
                break
            time.sleep(POLL_INTERVAL_SECONDS)

        if cancellation_unconfirmed:
            # Never reached a terminal state within the confirmation window
            # -- see CODEX_REVIEW.md finding H-1. This is the fix's whole
            # point: report honestly that we don't know, rather than saying
            # "cancelled" just because Stop was pressed. Nothing terminal
            # means nothing to collect results from, so this ends the run
            # here rather than falling through to output-writing below.
            minutes = CANCELLATION_CONFIRMATION_TIMEOUT_SECONDS // 60
            write_off_peak_job_state(
                provider=provider, model=model, job_id=job_id,
                submitted_at=submitted_at_iso, status="status_unknown",
            )
            with lock:
                state["summary"] = (
                    f"Off-peak batch cancellation could not be confirmed after {minutes} minutes -- "
                    f"job {job_id} ({provider}) may still be running (and billing) on the provider's "
                    "own servers. This app has no way to force-stop it from here: check the "
                    "provider's own console/dashboard for its actual status. This job's id is saved "
                    "and will be shown again the next time this app starts, until you dismiss it "
                    "(Reset All)."
                )
                state["log"].append(f"[{_log_timestamp()}] {state['summary']}")
                state["log"] = state["log"][-300:]
                state["download"] = ""
            return

        # The loop only ever breaks (as opposed to raising) via `if
        # terminal: break` above, so `job` is guaranteed to be the
        # just-polled, terminal job object at this point -- there is no
        # "cancelled before a single poll succeeded" case left to handle
        # separately (there used to be one; see CODEX_REVIEW.md finding H-1
        # for why that path could report a false "cancelled" too).
        if provider == "claude":
            try:
                results = collect_claude_batch_results(heavy_client, job_id)
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"The off-peak batch (job {job_id}) reached a terminal state on the provider's "
                    f"side, but downloading its results did not finish within "
                    f"{BATCH_SUBMIT_TIMEOUT_SECONDS}s -- the connection stalled. The job itself is "
                    "unaffected; check the provider's own console, or try again to re-download the "
                    "results."
                ) from exc
        else:
            results = collect_gemini_batch_results(job)

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
                next_name, previous_name = physical_neighbors(names, index, reverse_order)
                output.write(render_entry(name, entry_text, next_name, previous_name))

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
        really_cancelled = cancelled and _batch_was_cancelled(provider, job)
        with lock:
            if really_cancelled:
                state["summary"] = f"Off-peak batch cancelled after {len(image_results)} image(s), {failures} failure(s)."
            elif cancelled:
                # Stop was requested, but the job's own terminal state
                # doesn't actually show a cancellation -- it finished
                # (successfully or not) before the cancel request took
                # effect. Results are fully real either way; only the
                # wording changes, so this isn't reported as a cancellation
                # that didn't happen. See CODEX_REVIEW.md finding H-1.
                state["summary"] = (
                    f"Off-peak batch finished processing before cancellation took effect: "
                    f"{len(image_results)} image(s), {failures} failure(s)."
                )
            else:
                state["summary"] = f"Off-peak: processed {len(image_results)} image(s), {failures} failure(s)."
            state["log"].append(f"[{_log_timestamp()}] {state['summary']}")
            state["log"] = state["log"][-300:]
            state["download"] = str(docx_file) if docx_file.exists() else ""
        # Fully resolved -- nothing left to recover after a restart.
        clear_off_peak_job_state()
    except Exception as exc:
        message = humanize_provider_error(exc, model)
        if job_id:
            write_off_peak_job_state(
                provider=provider, model=model, job_id=job_id,
                submitted_at=submitted_at_iso, status="status_unknown",
            )
        with lock:
            state["log"].append(f"[{_log_timestamp()}] Fatal error: {message}")
            state["log"] = state["log"][-300:]
            state["summary"] = f"Fatal error: {message}"
    finally:
        with lock:
            state["running"] = False
            state["off_peak"] = False
