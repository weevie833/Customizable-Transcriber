# Security Policy

## Supported versions

This is a single-maintainer local tool with no LTS branches — only the
latest commit on `main` (and the latest tagged `VERSION`) is supported.
There's no backport process for older releases; if you're not on the
latest version, update first before reporting.

## Reporting a vulnerability

Please **do not open a public GitHub issue** for a security report.

Use GitHub's private vulnerability reporting instead: go to this repo's
[**Security** tab → **Report a vulnerability**](https://github.com/weevie833/Customizable-Transcription/security/advisories/new).
This opens a private advisory only the maintainer can see until it's
resolved, and lets you attach a proof-of-concept safely.

Please include:

- What you found and where (file/function, or a reproduction script)
- What it lets an attacker do
- Any suggested fix, if you have one

This project has no dedicated security team or SLA — it's maintained by one
person in their spare time — but reports are taken seriously and will get a
response and, for anything confirmed, a fix. If you haven't heard back
within a couple of weeks, a follow-up comment on the advisory is welcome.

## Scope

This app runs entirely on `127.0.0.1`/`localhost` for one local user — it's
not deployed as a multi-tenant or internet-facing service, and its threat
model is built around that: defenses against cross-site requests reaching
the local server (CSRF/Host/Origin checks), malicious input files (a
crafted `.docx`/image), and
supply-chain issues in its own dependencies. Reports along those lines are
very much in scope. Reports assuming a different deployment model (e.g.
"this would be exploitable if exposed to the internet without a reverse
proxy") are useful context but not urgent, since that isn't how this app is
meant to run.
