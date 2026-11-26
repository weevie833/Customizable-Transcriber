"""Off-peak option for the Transcribe page's "Translate completed transcript"
section: the same translation requests a real-time run would make
(transcript_translation._chunks()/chunk_message()), sent as one provider
batch (Gemini `client.batches`, Anthropic `client.messages.batches`) at
roughly half the per-token price.

What is shared, so the two runs can't drift apart:
- the plan, the prompt, the request grouping and each request's JSON
  (transcript_translation.py);
- matching a response back to its entries (read_chunk_response()) and
  writing the document, the .md and the report (write_translation_outputs());
- polling, cancelling and the job record kept for a restart
  (batch_transcription.watch_batch(), TranscribeOffPeakSink).

What differs: a real-time request that is cut off at the output limit is
retried at once in two halves. A batch can't do that, so any request whose
batch result failed, was cut off, or wasn't valid JSON is re-sent in real
time once the batch has finished (_translate_chunk(), which still splits a
cut-off request). Stop during the batch cancels it; Stop during that
real-time step stops before the next request. Either way the entries that
were translated are kept in the document.

Like the transcription off-peak job, a batch submitted before an app restart
can't be watched again (the API key is never saved); its job record is shown
at the next start until Reset All.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime

import anthropic
import httpx
from google.genai import types as genai_types

from app_state import add_log, lock, state
from batch_transcription import (
    BATCH_STATUS_TIMEOUT_SECONDS,
    BATCH_SUBMIT_TIMEOUT_SECONDS,
    CANCELLATION_CONFIRMATION_TIMEOUT_SECONDS,
    CLAUDE_BATCH_MAX_REQUEST_BYTES,
    BatchSubmissionError,
    ItemError,
    SubmissionStopped,
    TranscribeOffPeakSink,
    _batch_was_cancelled,
    _check_stop,
    _claude_client,
    _gemini_client,
    _log_timestamp,
    _send_if_not_stopped,
    gemini_batch_counts,
    item_error_for_log,
    provider_item_error,
    safe_batch_item_error,
    watch_batch,
)
from customizable_transcriber import stop_reasons, usage_ledger
from customizable_transcriber.core import (
    ensure_key_matches_model,
    gemini_sampling_kwargs,
    humanize_provider_error,
    provider_for_model,
    validate_api_key_with_retry,
)
from profiles_store import PROJECT_DIR
from transcript_translation import (
    PROMPT_VERSION,
    Entry,
    Plan,
    TranslationOptions,
    _chunks,
    _translate_chunk,
    build_plan,
    build_translation_prompt,
    chunk_message,
    entry_label,
    plan_output_names,
    progress_span,
    read_chunk_response,
    write_translation_outputs,
)
from xls_conversion.ai_parser import CLAUDE_JSON_MAX_TOKENS, GEMINI_JSON_MAX_OUTPUT_TOKENS, _parse_json_response

# A batch result that never produced an answer because the batch was
# cancelled or ran out of time: after a Stop these entries are "not
# translated (stopped)", not problems.
_NOT_RUN = "not_run"
_FAILED = "failed"


# --- Submitting ------------------------------------------------------------


def _gemini_json_config(model: str, system_prompt: str) -> genai_types.GenerateContentConfig:
    """The same settings call_gemini_json() (xls_conversion/ai_parser.py)
    uses for a real-time translation request, with the system prompt sent in
    full (a batch has no context cache)."""
    options: dict[str, object] = {
        "system_instruction": system_prompt,
        "response_mime_type": "application/json",
        "max_output_tokens": GEMINI_JSON_MAX_OUTPUT_TOKENS,
        **gemini_sampling_kwargs(model),
    }
    if model.startswith(("gemini-3", "gemini-4")) and hasattr(genai_types, "ThinkingConfig"):
        options["thinking_config"] = genai_types.ThinkingConfig(thinking_level=genai_types.ThinkingLevel.MEDIUM)
    return genai_types.GenerateContentConfig(**options)


def submit_gemini_text_batch(
    client, model: str, system_prompt: str, messages: list[str], *, should_stop=None, before_send=None
) -> str:
    """One inlined request per message, tagged with its position (never a
    filename), as submit_gemini_batch() does for images."""
    config = _gemini_json_config(model, system_prompt)
    requests = []
    for index, message in enumerate(messages):
        _check_stop(should_stop)
        requests.append(
            genai_types.InlinedRequest(model=model, contents=message, config=config, metadata={"index": str(index)})
        )
    _send_if_not_stopped(before_send)
    job = client.batches.create(
        model=model,
        src=requests,
        config=genai_types.CreateBatchJobConfig(
            display_name=f"customizable-transcriber-translate-{uuid.uuid4().hex[:12]}"
        ),
    )
    return job.name


def _claude_request(index: int, model: str, system_prompt: str, message: str) -> dict:
    # Same settings as call_claude_json() (xls_conversion/ai_parser.py).
    return {
        "custom_id": str(index),
        "params": {
            "model": model,
            "max_tokens": CLAUDE_JSON_MAX_TOKENS,
            "output_config": {"effort": "high"},
            "system": system_prompt,
            "messages": [{"role": "user", "content": message}],
        },
    }


def claude_batch_bytes(model: str, system_prompt: str, messages: list[str]) -> int:
    return sum(
        len(json.dumps(_claude_request(index, model, system_prompt, message)).encode("utf-8"))
        for index, message in enumerate(messages)
    )


def submit_claude_text_batch(
    client, model: str, system_prompt: str, messages: list[str], *, should_stop=None, before_send=None
) -> str:
    requests = []
    for index, message in enumerate(messages):
        _check_stop(should_stop)
        requests.append(_claude_request(index, model, system_prompt, message))
    _send_if_not_stopped(before_send)
    # No automatic retry: creating a batch is not idempotent, so a retry after
    # a lost response could create a second paid batch (as submit_claude_batch()).
    batch = client.with_options(max_retries=0).messages.batches.create(requests=requests)
    return batch.id


# --- Collecting ------------------------------------------------------------


def _outcome(provider: str, text: str, reason: object) -> tuple[str, str]:
    """("", "") for a complete answer, else (kind, error) where kind says
    whether the request is worth re-sending (always, for a translation:
    nothing partial is kept)."""
    if not text.strip():
        return _FAILED, stop_reasons.empty_error(reason)
    outcome = stop_reasons.classify(provider, reason)
    if outcome == stop_reasons.BLOCKED:
        return _FAILED, stop_reasons.blocked_error(reason)
    if outcome == stop_reasons.TRUNCATED:
        return _FAILED, "The AI response was cut off at the output limit."
    if outcome == stop_reasons.INCOMPLETE:
        return _FAILED, f"The AI response did not finish ({stop_reasons.reason_text(reason)})."
    return "", ""


def collect_gemini_text_results(job, usage_sink: list) -> dict[int, tuple[str, str, str]]:
    """index -> (text, kind, error); kind is "" for a usable answer."""
    results: dict[int, tuple[str, str, str]] = {}
    for item in (job.dest.inlined_responses if job.dest else None) or []:
        try:
            index = int((item.metadata or {}).get("index", ""))
        except ValueError:
            continue
        if item.error:
            results[index] = ("", _FAILED, provider_item_error(item.error.message or item.error))
            continue
        response = item.response
        text = (response.text if response else "") or ""
        candidates = (getattr(response, "candidates", None) or []) if response else []
        reason = getattr(candidates[0], "finish_reason", None) if candidates else None
        kind, error = _outcome("gemini", text, reason)
        results[index] = (text, kind, ItemError(error) if error else "")
        if response is not None:
            usage_sink.append(
                {"index": index, "usage": getattr(response, "usage_metadata", None),
                 "finish_reason": reason, "text_chars": len(text)}
            )
    return results


def collect_claude_text_results(client, batch_id: str, usage_sink: list) -> dict[int, tuple[str, str, str]]:
    results: dict[int, tuple[str, str, str]] = {}
    for item in client.messages.batches.results(batch_id):
        try:
            index = int(item.custom_id)
        except ValueError:
            continue
        result = item.result
        if result.type == "succeeded":
            text = "".join(block.text for block in result.message.content if block.type == "text")
            reason = getattr(result.message, "stop_reason", None)
            kind, error = _outcome("claude", text, reason)
            results[index] = (text, kind, ItemError(error) if error else "")
            usage_sink.append(
                {"index": index, "usage": getattr(result.message, "usage", None),
                 "finish_reason": reason, "text_chars": len(text)}
            )
        elif result.type == "errored":
            results[index] = ("", _FAILED, provider_item_error(result.error))
        else:
            results[index] = ("", _NOT_RUN, ItemError(f"Request was {result.type}."))
    return results


# --- The job ---------------------------------------------------------------


class TranslationOffPeakSink(TranscribeOffPeakSink):
    """The Transcribe page's off-peak sink; the record is marked as a
    translation so a leftover one can be told apart."""

    def persist(self, **fields: object) -> bool:
        return super().persist(kind="translation", **fields)


def _record_usage(
    *, provider, model, system_prompt, chunks, results, usage_sink, profile, job_id, submitted_at, counts, languages
) -> None:
    run = usage_ledger.start_run(
        mode="off_peak",
        stage="translate",
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        profile_id=str(profile.get("id", "")),
        profile_label=str(profile.get("label", "")),
        prompt_version=PROMPT_VERSION,
        languages=languages,
        job_id=job_id,
        submitted_at=submitted_at,
        provider_counts=counts,
    )
    for item in usage_sink:
        index = item["index"]
        usage_ledger.record_call(
            provider=provider,
            model=model,
            usage=item["usage"],
            finish_reason=item["finish_reason"],
            text_chars=item["text_chars"],
            cache_expected=False,
            run=run,
            image=chunks[index][0].record if 0 <= index < len(chunks) else str(index),
        )
    usage_ledger.end_run(run, requests=len(chunks), failures=sum(1 for _t, kind, _e in results.values() if kind))


def _read_batch(
    chunks: list[list[Entry]], plan: Plan, results: dict[int, tuple[str, str, str]], cancelled: bool
) -> tuple[dict, dict, dict[str, str], list[Entry]]:
    """(translations, church wedding translations, failures, entries to
    re-send). After a Stop, requests the batch never ran are left untranslated
    (stopped) and nothing is re-sent."""
    translations: dict[str, dict[str, str]] = {}
    cwr: dict[str, dict[str, str]] = {}
    failures: dict[str, str] = {}
    resend: list[Entry] = []
    for index, chunk in enumerate(chunks):
        text, kind, error = results.get(index, ("", _NOT_RUN, ItemError("No result was returned for this request.")))
        if kind == _NOT_RUN and cancelled:
            continue
        if kind:
            add_log(f"[{_log_timestamp()}] {chunk[0].record}: {item_error_for_log(error)}")
            reason = safe_batch_item_error(error)
            chunk_failures = {entry.entry_id: reason for entry in chunk}
        else:
            try:
                response = _parse_json_response(text)
            except RuntimeError as exc:
                chunk_failures = {entry.entry_id: str(exc) for entry in chunk}
            else:
                done, cwr_done, chunk_failures = read_chunk_response(chunk, plan, response)
                translations.update(done)
                cwr.update(cwr_done)
        failures.update(chunk_failures)
        resend += [entry for entry in chunk if entry.entry_id in chunk_failures]
    return translations, cwr, failures, resend


def _resend_in_real_time(
    entries: list[Entry], plan: Plan, model: str, api_key: str, system_prompt: str, sink
) -> tuple[dict, dict, dict[str, str], bool]:
    """The batch's failed requests, sent again one by one. Returns
    (translations, church wedding translations, failures, stopped)."""
    translations: dict[str, dict[str, str]] = {}
    cwr: dict[str, dict[str, str]] = {}
    failures: dict[str, str] = {}
    stopped = False
    chunks = _chunks(entries, plan)
    unit = "pages" if plan.line_structure else "entries"
    with lock:
        # The batch is over: Stop now means "stop after the current request",
        # as in a real-time run, and the Progress Console words it that way.
        state["off_peak"] = False
    add_log(f"[{_log_timestamp()}] Re-sending {len(entries)} {unit} the batch could not translate, in real time "
            f"({len(chunks)} request(s)).")
    profile = plan.profile or {}
    run = usage_ledger.start_run(
        mode="regular", stage="translate", provider=provider_for_model(model), model=model,
        system_prompt=system_prompt, profile_id=str(profile.get("id", "")),
        profile_label=str(profile.get("label", "")), prompt_version=PROMPT_VERSION, languages=plan.languages,
        resend_after_off_peak=True,
    )
    token = usage_ledger.activate(run)
    try:
        for number, chunk in enumerate(chunks, start=1):
            if sink.stop_requested():
                stopped = True
                # Entries not reached are left out of failures, so the report
                # lists them as "Not translated (stopped)".
                add_log("Stopped before the next request.")
                break
            add_log(f"[{number}/{len(chunks)}] {chunk[0].record}, {progress_span(chunk, plan)}")
            with usage_ledger.image_context(chunk[0].record):
                done, cwr_done, failed = _translate_chunk(chunk, plan, api_key, model, system_prompt, None, False)
            translations.update(done)
            cwr.update(cwr_done)
            failures.update(failed)
            for entry in chunk:
                if entry.entry_id in failed:
                    add_log(f"Problem with {entry_label(entry)}: {failed[entry.entry_id]}")
    finally:
        usage_ledger.deactivate(token)
        usage_ledger.end_run(run, translated=len(translations), failures=len(failures), stopped=stopped)
    return translations, cwr, failures, stopped


def run_off_peak_translation_job(
    text: str,
    source_name: str,
    profile_id: str,
    languages: list[str],
    model: str,
    api_key: str,
    options: TranslationOptions | None = None,
    sink: TranslationOffPeakSink | None = None,
) -> None:
    """Background thread for one off-peak translation. The caller has already
    reserved state["running"] and set state["off_peak"]; sink.released()
    always clears both."""
    sink = sink or TranslationOffPeakSink()
    started = datetime.now()
    job_id = ""
    submitted_at = ""
    provider = provider_for_model(model)
    try:
        plan = build_plan(text, profile_id, languages, options)
        if plan.errors:
            raise RuntimeError(" ".join(plan.errors))
        names = plan_output_names(source_name)
        system_prompt = build_translation_prompt(
            plan.profile, plan.native_language, plan.languages, plan.options, line_structure=plan.line_structure
        )
        if not plan.profile:
            add_log("No saved prompt profile was found; translating without background on the register.")
        entries = plan.entries_to_translate
        chunks = _chunks(entries, plan)
        messages = [chunk_message(chunk, plan) for chunk in chunks]
        unit = "pages" if plan.line_structure else "entries"
        add_log(
            f"Off-peak: translating {len(entries)} {unit} into {', '.join(plan.languages)} with {model} "
            f"as one batch ({len(chunks)} request(s))."
        )
        ensure_key_matches_model(model, api_key)
        add_log("Checking API key...")
        validate_api_key_with_retry(PROJECT_DIR, model, api_key, progress=add_log)
        add_log("API key validated.")
        if provider == "claude":
            size = claude_batch_bytes(model, system_prompt, messages)
            if size > CLAUDE_BATCH_MAX_REQUEST_BYTES:
                raise BatchSubmissionError(
                    f"This translation is too large for one Claude batch ({size / 1_000_000:.0f} MB; the limit is "
                    f"{CLAUDE_BATCH_MAX_REQUEST_BYTES // 1_000_000} MB). Split the document, or run it in real time."
                )
            heavy = _claude_client(api_key, BATCH_SUBMIT_TIMEOUT_SECONDS)
            light = _claude_client(api_key, BATCH_STATUS_TIMEOUT_SECONDS)
            submit = submit_claude_text_batch
        else:
            heavy = _gemini_client(api_key, BATCH_SUBMIT_TIMEOUT_SECONDS)
            light = _gemini_client(api_key, BATCH_STATUS_TIMEOUT_SECONDS)
            submit = submit_gemini_text_batch

        try:
            job_id = submit(
                heavy, model, system_prompt, messages,
                should_stop=sink.stop_requested, before_send=sink.begin_submission,
            )
        except SubmissionStopped:
            sink.finished("Stopped before the off-peak translation batch was submitted.", None)
            return
        except (httpx.TimeoutException, httpx.RemoteProtocolError, anthropic.APIConnectionError) as exc:
            raise BatchSubmissionError(
                f"Submitting the off-peak translation batch ({len(chunks)} request(s)) did not finish within "
                f"{BATCH_SUBMIT_TIMEOUT_SECONDS}s. Submission outcome unknown: the provider may already have "
                f"accepted this batch and be running (and billing) it. Check your {provider.capitalize()} "
                "account's batch list/dashboard for a job submitted around now BEFORE trying again, so you "
                "don't pay for the same batch twice."
            ) from exc
        finally:
            sink.end_submission()

        submitted_at = datetime.now().isoformat(timespec="seconds")
        sink.persist(provider=provider, model=model, job_id=job_id, submitted_at=submitted_at, status="running")
        sink.submitted(
            provider, job_id, len(chunks),
            f"[{_log_timestamp()}] Off-peak translation batch submitted ({len(chunks)} request(s), job {job_id}). "
            "Processed on the provider's own schedule -- this may take a while.",
        )
        job, cancelled, unconfirmed = watch_batch(
            provider=provider, light_client=light, job_id=job_id, model=model,
            submitted_at=submitted_at, total=len(chunks), sink=sink,
        )
        if unconfirmed:
            saved = sink.persist(
                provider=provider, model=model, job_id=job_id, submitted_at=submitted_at, status="status_unknown"
            )
            sink.finished(
                f"Off-peak translation batch cancellation could not be confirmed after "
                f"{CANCELLATION_CONFIRMATION_TIMEOUT_SECONDS // 60} minutes -- job {job_id} ({provider}) may "
                "still be running (and billing). Check the provider's own console/dashboard. "
                + ("The job id is saved and will be shown again the next time this app starts, until Reset All."
                   if saved else "The job id could NOT be saved -- copy it from this message now."),
                None,
            )
            return

        usage_sink: list[dict] = []
        if provider == "claude":
            results = collect_claude_text_results(heavy, job_id, usage_sink)
        else:
            results = collect_gemini_text_results(job, usage_sink)
        _record_usage(
            provider=provider, model=model, system_prompt=system_prompt, chunks=chunks, results=results,
            usage_sink=usage_sink, profile=plan.profile or {}, job_id=job_id, submitted_at=submitted_at,
            counts=gemini_batch_counts(job) if provider != "claude" else {}, languages=plan.languages,
        )
        translations, cwr_translations, failures, resend = _read_batch(chunks, plan, results, cancelled)
        stopped = cancelled and _batch_was_cancelled(provider, job)
        resent = 0
        if resend and not cancelled:
            resent = len(resend)
            done, cwr_done, still_failed, stopped = _resend_in_real_time(
                resend, plan, model, api_key, system_prompt, sink
            )
            for entry in resend:
                failures.pop(entry.entry_id, None)
            translations.update(done)
            cwr_translations.update(cwr_done)
            failures.update(still_failed)
        elif cancelled and not stopped:
            add_log(f"[{_log_timestamp()}] The batch finished before the cancellation took effect; "
                    "failed requests were not re-sent.")

        run_note = (
            f"Run off-peak: provider batch {job_id} ({provider}), {len(chunks)} request(s), submitted {submitted_at}."
            + (f" {resent} {unit} the batch could not translate were re-sent in real time." if resent else "")
        )
        write_translation_outputs(
            plan, source_name, names, model, translations, cwr_translations, failures,
            stopped, {}, started, len(entries), run_note=run_note, summary_prefix="Off-peak: ",
        )
        sink.clear_persisted()
    except Exception as exc:
        message = humanize_provider_error(exc, model)
        if job_id:
            sink.persist(provider=provider, model=model, job_id=job_id, submitted_at=submitted_at,
                         status="status_unknown")
        sink.failed(message)
    finally:
        sink.released()


def start_off_peak_translation_job(
    text: str, source_name: str, profile_id: str, languages: list[str], model: str, api_key: str,
    options: TranslationOptions,
) -> None:
    with lock:
        state["off_peak"] = True
        state["batch_provider"] = ""
        state["batch_job_id"] = ""
        state["batch_counts"] = {}
    threading.Thread(
        target=run_off_peak_translation_job,
        args=(text, source_name, profile_id, languages, model, api_key, options),
        daemon=True,
    ).start()
