# Human Decisions Required

Review date: 2026-11-13

Reviewed revision: `2aaddbd`

One current product/support decision is required. The other corrective actions in `reviews/CODEX_REVIEW.md` can be made without changing product or data policy.

## HD-1 — Embedded Python support and upgrade policy

Related finding: `CODEX_REVIEW.md` H-1.

### Decision needed

Choose the supported embedded Python line and binary source for Windows and macOS, and define how an installed runtime is upgraded and rolled back when the application folder is replaced.

Python `3.12.10`, currently installed on Windows, is no longer acceptable: it has been superseded by six security releases. Both installers also preserve any executable base interpreter indefinitely, so changing the pinned download in a later ZIP does not update existing users.

### Recommended choice

- Use the same reputable, reproducible standalone-Python distributor on both platforms where practical, pinned to an archive digest.
- Move to a currently security-supported patch release immediately. If remaining on 3.12 temporarily, use 3.12.16 or later security-equivalent builds on both platforms; otherwise adopt a current maintained feature line after dependency and application compatibility testing.
- Store an app-owned runtime manifest outside the virtual environment containing implementation, exact version, distributor/build ID, platform/architecture, and archive digest.
- On every launch, compare the expected manifest with the installed runtime. If it differs, download and verify into a staging directory, build/test the venv there, then atomically replace the runtime. Keep the previous runtime until the new one starts successfully so rollback is possible.
- Treat `requirements.lock` equality as a separate package-layer decision; it must not stand in for interpreter currency.
- Test clean install, unchanged restart, package-only update, interpreter security update, failed update/rollback, and moved-application-folder scenarios in CI.

### Human input required

- Which Python feature line is supported for packaged users: patched 3.12 temporarily, or a move to 3.14/3.15?
- Which binary distributor is trusted on each platform?
- Must runtime security updates occur automatically at first launch of a new app version, or may the app block and require explicit confirmation?
- How long should the previous runtime be retained for rollback?

## Retained decisions that do not need reopening

| Area | Current decision |
|---|---|
| Local authentication | Single-user localhost use only; other local processes/users are outside the supported threat model. |
| Credentials | Browser flows do not persist provider API keys; ignored `.env` fallback remains optional. |
| Off-Peak recovery | Ambiguous submissions require provider-dashboard reconciliation; non-secret job metadata is persisted when an ID is known. |
| Off-Peak capacity | 500 MB raw aggregate / 1,000 images is the interim supported envelope; larger jobs are split manually. |
| Profile concurrency | Stale-tab edits remain last-writer-wins. |
| Browser tests | Browser automation remains deferred. |
| Lint | Ruff remains advisory; cleanup/no-new-warning enforcement can proceed without changing product behavior. |
| Supply chain | Exact version locks are required; hash locks and Action commit-SHA pins remain optional defense in depth. |

OVERALL STATUS: HUMAN_DECISION_REQUIRED
