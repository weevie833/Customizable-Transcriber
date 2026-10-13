# Human Decisions Required

Review date: 2026-09-20

Reviewed revision: `a4e3328`

Four current decisions are required. All other corrective actions in `CODEX_REVIEW.md` can be made without changing product or data policy.

## HD-1 — Ambiguous Off-Peak submission recovery

Related finding: `CODEX_REVIEW.md` H-1.

### Decision needed

Define what the app must do when a provider may have accepted a paid batch but the create response, and therefore the job ID, was lost.

### Recommended choice

Treat submission timeout as **outcome unknown**, not failure:

- Persist a non-secret `submitting` record before the call with provider, unique local run ID, timestamp, image count, and request fingerprint.
- Disable SDK retries for create unless the provider offers a documented idempotency key and that key is actually sent.
- Use a unique Gemini display name and provider-list/dashboard reconciliation where feasible.
- Do not invite immediate retry. Require the user to check/reconcile the provider account first, then explicitly acknowledge whether resubmission is safe.
- Never persist the API key.

### Lower-scope alternative

Disable automatic create retries and change the timeout message to “submission outcome unknown; check the provider dashboard before retrying.” This does not recover the ID automatically, but it avoids positively encouraging duplication.

### Human input required

- Must the app reconcile ambiguous submissions itself, or is provider-dashboard recovery acceptable?
- May a user resubmit after acknowledgement without confirmed reconciliation?
- Is a unique non-secret submission fingerprint acceptable in persisted state?

## HD-2 — Continuation merge conflict policy

Related finding: `CODEX_REVIEW.md` H-2.

### Decision needed

Define which value wins when the original departure-image row and the context-aware continuation merge disagree.

### Recommended choice

Use conservative field-level merge rules:

- A blank continuation value never erases a prior non-empty value.
- Stable identity, date, act/page locator, and source-image fields remain from the original unless a conflict is explicitly surfaced for human review.
- New continuation-only facts fill blanks or append to suitable notes/list fields.
- Conflicting non-empty values keep the original in the export and enter a visible review/exception log containing both values.
- If invariants cannot be satisfied, keep both source rows rather than silently replacing the original.

### Alternative

Allow the context-aware merge to override prior values, but retain an audit copy/diff of the original and flag every changed non-empty field for review.

### Human input required

- Should a later, context-rich extraction ever automatically override a prior non-empty value?
- Which fields are immutable, append-only, or review-required for each record type?
- Should unresolved conflicts block export or merely produce warnings?

## HD-3 — Prompt Builder preflight ground-truth scope

Related finding: `CODEX_REVIEW.md` M-1.

### Decision needed

Decide whether a preflight run validates only content visible on one uploaded image or an entire multi-image example.

### Recommended choice

Keep the current one-image workflow. Serialize Date, Main entry, and the applicable Baptism/Church Wedding side-column block as ground truth for that image. Exclude the Continuation field because it is explicitly the opening of the next image. Label this scope in the UI.

### Alternative

Permit two image uploads for examples with continuations and run/compare both images as one linked preflight. This is more complete but increases provider cost, latency, UI complexity, and test surface.

### Human input required

- Is one-image validation sufficient?
- If so, should continuation be ignored or should preflight reject examples containing it with an explanation?
- If paired-image validation is required, is the additional cost/latency acceptable?

## HD-4 — Supported Off-Peak memory envelope

Related finding: `CODEX_REVIEW.md` M-2.

### Decision needed

Replace the unmeasured 2 GB raw-input default with a limit tied to supported host memory and real batch requirements, or require a staging/streaming design.

### Recommended choice

Measure peak resident memory for Gemini and Claude, including base64 and HTTP serialization, on the minimum supported host. Set provider-specific aggregate limits with safety headroom and reject larger folders before reading bodies. Until that evidence exists, adopt a materially conservative temporary cap and instruct users to split batches.

If multi-gigabyte batches are a product requirement, move payloads to provider-side file staging or another bounded mechanism; do not raise the in-memory limit.

### Human input required

- What is the minimum supported RAM configuration?
- What are the largest legitimate batch size and total raw bytes?
- Is manual folder splitting acceptable, or must very large batches be handled transparently?

### Status (SECURITY_REVIEW_4.md SEC-4-01)

Interim cap of 500 MB aggregate / 1,000 images is in force and documented in `docs/DESIGN.md` ("Off-Peak memory envelope"). Streaming/staging is deferred until a real multi-GB requirement exists.

## Previously resolved constraints retained

| Area | Existing decision |
|---|---|
| Local authentication | Single-user machine only; other local OS users/processes are out of scope and documented in `SECURITY.md`. |
| Credentials | Browser batch flows do not persist API keys; ignored `.env` fallback remains for documented tools. |
| Off-Peak cancellation | Persist non-secret job metadata, wait for provider-confirmed terminal state, and use manual dashboard recovery after restart. |
| Profile concurrency | Last-writer-wins across stale browser tabs is accepted. |
| Browser tests | Browser automation remains deferred; Python/HTTP regressions are preferred for now. |
| Lint | Ruff remains informational/non-blocking in CI. |
| Dormant parsers | Retain the three legacy regex parsers as documented reference code. |
| Supply chain | Exact direct/tool pins are used; fully locked transitives and commit-SHA GitHub Actions are not currently required. |

OVERALL STATUS: HUMAN_DECISION_REQUIRED
