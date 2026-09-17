# Human Decisions Required

Review date: 2026-09-16

Reviewed revision: `e420b3f`

Two current decisions are required. Every other corrective action in `CODEX_REVIEW.md` can be implemented without changing product policy.

## HD-1 — Off-Peak cancellation and recovery contract

Related finding: `CODEX_REVIEW.md` H-1.

### Decision needed

Choose what the application must do when the provider does not promptly confirm a cancellation, and whether an in-flight provider/job identifier must survive application restart.

### Recommended choice

Persist only the non-secret provider name, job ID, submission time, and local output metadata. Use distinct states:

- `running`
- `cancellation requested`
- `cancellation confirmed`
- `completed`
- `failed`
- `status unknown; check provider`

After Stop, continue bounded polling until a terminal provider state is observed. Never display `cancelled` merely because the local cancel request was sent. If confirmation times out, retain and display the job ID with provider-dashboard instructions, and allow a later status/recovery attempt. Never persist the API key.

### Lower-scope alternative

Retain the current no-persistence policy, but still stop claiming cancellation without confirmation. Show `cancellation unconfirmed`, keep the job ID visible for the lifetime of the process, and clearly direct the user to the provider console. This is less robust across restart but fixes the dangerous false-success claim.

### Unacceptable option

Keep the current behavior. A failed cancellation can leave a paid provider job running while the application states that it was cancelled and discards its tracking state.

### Human input required

- May the existing “no job state on disk” v1 constraint be reversed for non-secret job metadata?
- How long should cancellation confirmation be retried before the state becomes `unknown`?
- Should the application support reconnect/recover after restart, or only provide the job ID for manual provider-console recovery?

## HD-2 — Off-Peak batch capacity and scaling policy

Related finding: `CODEX_REVIEW.md` M-2.

### Decision needed

Define the maximum supported Off-Peak batch by item count and aggregate source bytes, or require a provider file-upload/streaming design for larger workloads.

### Recommended choice

Adopt explicit per-provider limits derived from the provider APIs and the minimum supported host-memory budget. Reject the batch before any file body is read if either the item count or aggregate bytes exceeds its limit. Display the calculated count/bytes and tell the user how to split the folder. Revalidate each file at consumption time.

If the intended product requirement is effectively unlimited archival batches, do not solve that by selecting a very large memory cap; use provider-side files or another bounded streaming/staging mechanism so the process does not retain every raw/base64 payload simultaneously.

### Unacceptable option

Keep only the current 50 MB per-file limit. It permits multi-gigabyte aggregate request construction and does not address the validation/read race.

### Human input required

- What is the largest legitimate batch, by image count and aggregate bytes?
- What is the minimum host-memory target?
- Is rejecting/splitting large folders acceptable, or must the app transparently stage/stream them?

## Previously resolved constraints retained

These prior maintainer decisions were considered during this review and are not being reopened:

| Area | Existing decision |
|---|---|
| Local authentication | Single-user machine only; other local OS users/processes are out of scope and documented in `SECURITY.md`. |
| Credentials | Batch tools require pasted keys; limited `.env` fallback remains for documented small tools; keys are not persisted by browser batch flows. |
| Per-file source safety | 50 MB maximum per source file; reject files and directory paths involving symlinks. |
| Profile concurrency | Last-writer-wins across stale browser tabs is accepted. |
| Browser tests | Browser automation is deferred; Python/HTTP regression coverage is preferred for now. |
| Lint | Ruff remains informational/non-blocking in CI. |
| Dormant parsers | Retain the three legacy regex parsers as explicitly documented reference code. |
| Supply chain | Exact direct/tool pins are used; fully locked transitives and commit-SHA GitHub Actions are not currently required. |

OVERALL STATUS: HUMAN_DECISION_REQUIRED
