# Data Processing & Privacy Notice

This document explains what happens to data when Transcription Bot is used,
who is responsible for what, and what to consider if you operate it in the
European Union or on behalf of a parish, diocese, or archive. It is written
to work for two audiences at once: an individual genealogist using this on
their own, and an institution (a parish, a diocesan archive) that wants
something it can show its own compliance office or data-protection officer.

**This is not legal advice.** It is a factual description of how the
software behaves, and a practical map of the compliance questions that
description raises. If you are processing records that could involve living
individuals, or you are deploying this on behalf of an institution, get
your own legal review before relying on this document.

## Intended use

Transcription Bot is built and tested against **historical archival church
and civil records** — the working examples throughout this project are
18th- and 19th-century baptism, marriage, and death registers. That
intended use matters for the compliance analysis below: GDPR's protections
apply to living individuals, and do not extend to the deceased (GDPR
Recital 27; a few EU member states extend some protections to the deceased
under their own national law — if that might apply to you, check locally).
Most of what this tool is designed to process falls outside GDPR's scope
for that reason alone.

**Nothing in the software enforces this.** It is a plain transcription and
extraction tool — it has no way to tell an 1850s register from a 2020s one,
and nothing stops it being pointed at recent records naming living people.
If you do that, the analysis in this document changes materially — see
"If your records involve living individuals" below.

## How the software is architected, and why that matters

Transcription Bot is a local application. You (or your institution) clone
the source code and run it entirely on your own machine — there is no
hosted service, no central server operated by the software's authors, and
no account system. Concretely:

- The people who publish this software **never receive, see, or store**
  any data you process with it. There is nothing for them to be a data
  controller or processor *of* — they have no visibility into your usage
  at all.
- Every file this app reads or writes — source images, transcriptions,
  exported spreadsheets, saved prompt profiles — lives on your own
  filesystem, under your own control, for as long as you keep it there.
  Deleting it is entirely in your hands; there is no vendor-side copy to
  separately request deletion of.
- The one exception to "stays on your machine" is the AI processing step
  itself — see below.

## Roles under GDPR: who is the controller here

GDPR distinguishes a **data controller** (decides why and how personal
data is processed) from a **data processor** (processes it on the
controller's instructions). Applied to this software:

- **The software's publisher is neither.** With no central server, there
  is no point at which the publisher processes anyone's data.
- **You are the controller** for whatever you process. This is true
  whether you are an individual researcher or a parish — the same
  obligation would exist if you did this work with a scanner and a
  spreadsheet instead of this app. The software can help you meet that
  obligation (or fail to help), but it cannot discharge it for you.
- **Google (Gemini) and Anthropic (Claude) act as processors** — or, more
  precisely, as the AI providers whose infrastructure your controller-role
  responsibilities extend to — for the specific step where the app sends
  content to their API for transcription or extraction. See below.

## What data this app actually sends to a third party, and to whom

When you run a transcription or an XLS Conversion extraction, the app
sends the following directly from your machine to the AI provider you
selected (Google Gemini or Anthropic Claude) — never through any server
the software's publisher operates:

- The **source image(s) or uploaded DOCX text** you're processing for that
  run.
- The **prompt content** describing how to transcribe/extract it (which
  may include a name/place lexicon you supplied, if your profile has one).
- Your own **API key**, to authenticate that request.

Nothing else leaves your machine. The app does not phone home, does not
send analytics or telemetry anywhere, and does not transmit anything to
the software's publisher.

**API key handling** (verified in this project's own production-readiness
audit): keys are held only in memory for the duration of the request that
uses them. They are never written to any file, never logged, and never
transmitted anywhere except the one AI provider's API endpoint you're
actively using.

## If your records involve living individuals

If you use this tool on material that names or concerns people who may
still be alive — a recent register, a witness or relative referenced in an
otherwise-historical entry, anything not clearly closed by time — you are
processing personal data in GDPR's full sense, and the analysis above
tightens considerably:

- **Church records are "special category" data.** A baptism, marriage, or
  death record inherently reveals religious affiliation, which GDPR
  Article 9 treats as a higher-sensitivity category than ordinary personal
  data, requiring a stronger lawful basis (explicit consent, or one of
  Article 9(2)'s other narrow grounds) than routine processing does.
- **You need your own lawful basis** for processing that data at all, and
  for sending it to Google or Anthropic specifically.
- **You need your own agreement with the AI provider.** Both Google and
  Anthropic offer Data Processing Agreements (DPAs) and rely on
  International/Standard Contractual Clauses (or comparable transfer
  mechanisms) for customers processing EU personal data through their
  APIs — but that agreement has to exist between *you* (or your
  institution) and the provider directly. This software cannot create or
  substitute for it. Check each provider's current terms directly, since
  the specific transfer mechanism they rely on changes over time.
- **International transfer**: Gemini and Claude API calls are processed on
  infrastructure outside the EU. Confirm your own arrangement with
  whichever provider you use relies on a currently-valid transfer
  mechanism for that reason alone, independent of the special-category
  question above.
- **If you're a parish or diocesan institution**, this is very likely the
  point at which your own data-protection officer or compliance office
  needs to be involved before deployment, not after.

## Data retention

This software imposes no retention policy of its own — there is nothing
for it to retain, since it holds no data outside the single request/response
cycle of each AI call. Whatever you keep (source images, transcriptions,
exported spreadsheets, saved profiles) is retained exactly as long as you
choose to keep the files on your own disk, and deleted exactly when you
delete them. If your institution has its own records-retention policy,
apply it the same way you would to any other local file.

## Your responsibilities as the operator

In summary, if you run this software, you are responsible for:

1. Confirming whether the material you're processing is within the
   historical-archive scope this tool is built for, or involves living
   individuals — and treating the two cases differently as described
   above.
2. Having a lawful basis for any processing of living individuals' data,
   with particular care given religious records' special-category status.
3. Having your own agreement in place with whichever AI provider(s) you
   use, if you are processing personal data of living individuals through
   them.
4. Applying your own (or your institution's) records-retention and
   deletion practices to the files this software produces.
5. Securing your own API keys and the machine this software runs on, the
   same as you would for any other tool handling sensitive material.

## Questions

This document describes the software's behavior as of the version you're
reading it alongside. If you have questions specific to your own
deployment — especially as an institution — route them through your own
legal or compliance function rather than relying solely on this notice.
