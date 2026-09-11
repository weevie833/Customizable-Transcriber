"""Generic HTTP-request parsing helpers shared by every handler mixin in
`handlers/` (and by app.py's own Handler methods that haven't moved out).

Split out of app.py as part of the Handler-method modularization pass (see
docs/DESIGN.md's "Codebase structure" section) for a specific reason: every
`handlers/*.py` mixin needs FormData/parse_post_form/parse_json_body/etc.,
but app.py itself imports those mixins to compose the Handler class -- if
these helpers stayed defined in app.py, every handlers/*.py module would
need to import them back from app.py, which imports handlers/*.py, which is
a circular import. Nothing here reads any handlers/*.py or app.py name, so
importing in either direction is safe.

Also owns the request-size caps (MAX_FORM_BYTES/MAX_DOCX_BYTES/
MAX_JSON_BYTES/MAX_DOCX_XML_BYTES) and PREFLIGHT_TIMEOUT_SECONDS, for the
same reason: more than one handlers/*.py module needs
PREFLIGHT_TIMEOUT_SECONDS (Prompt Builder's Preflight Test and XLS
Conversion's three AI-calling endpoints each bound their own AI calls to
it), so it can't live in just one of them without the others importing
across handler-module boundaries.
"""

from __future__ import annotations

import io
import json
import re
import urllib.parse
import zipfile
from collections.abc import Mapping
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from xml.etree import ElementTree

MAX_FORM_BYTES = 5_000_000
MAX_DOCX_BYTES = 50_000_000
MAX_JSON_BYTES = 15_000_000
# Caps the *decompressed* size of word/document.xml specifically -- MAX_DOCX_BYTES
# above only bounds the compressed upload, and a small, deliberately-repetitive
# zip entry can expand far past that (verified: a ~0.5MB crafted file decompressed
# to 1GB+ in memory with no cap in place). 20MB is generous for a transcription's
# worth of plain text/XML markup -- a real Word document.xml this large would
# already be an unusually long document.
MAX_DOCX_XML_BYTES = 20_000_000
# Per-call cap for every foreground, single-request handler that makes a
# real AI call: Prompt Builder's Preflight Test (handlers/profiles.py) and
# XLS Conversion's preflight_xls_source()/detect_xls_languages()/
# parse_xls_source() (handlers/xls_conversion.py), each of which passes this
# to its own validate_api_key_with_retry() cheap-key-check call as well as
# (for Prompt Builder) the real test call -- matches xls_conversion/
# ai_parser.py's own AI_REQUEST_TIMEOUT_SECONDS, which bounds those handlers'
# real extraction calls the same way via a separately constructed client, so
# every AI call these handlers make is bounded by the same value even though
# each call builds its own client. A given handler can make more than one
# such call (Prompt Builder's Preflight Test makes three: the key check,
# transcribe, then critique), so the request as a whole can take a multiple
# of this before giving up -- each individual call still fails cleanly with
# a clear error at this bound rather than hanging indefinitely, which is
# what a client with no timeout set does. The real Transcribe/Test Mode
# page's batch runs deliberately keep no such cap on their own key check or
# per-image calls -- see make_client()'s own comment; those run in a
# background job thread with a progress log and Stop support, not a single
# blocking foreground request.
PREFLIGHT_TIMEOUT_SECONDS = 90


class FormData:
    def __init__(self, values: Mapping[str, list[str]]) -> None:
        self.values = values

    def getfirst(self, name: str, default: str | None = None) -> str | None:
        values = self.values.get(name)
        if not values:
            return default
        return values[0]

    def setfirst(self, name: str, value: str) -> None:
        self.values[name] = [value]


def pasted_value(form: FormData, name: str) -> str:
    return (form.getfirst(name, "") or "").strip()


def parse_post_form(handler: BaseHTTPRequestHandler) -> FormData:
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise RuntimeError("Unsupported form submission type.")

    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Invalid form submission length.") from exc

    if content_length < 0 or content_length > MAX_FORM_BYTES:
        raise RuntimeError("Invalid form submission length.")

    body = handler.rfile.read(content_length).decode("utf-8")
    return FormData(urllib.parse.parse_qs(body, keep_blank_values=True))


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise RuntimeError("Unsupported request type.")
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Invalid request length.") from exc
    if content_length <= 0 or content_length > MAX_JSON_BYTES:
        raise RuntimeError("Invalid request length.")
    try:
        payload = json.loads(handler.rfile.read(content_length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The conversion request is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("The conversion request must be a JSON object.")
    return payload


def uploaded_docx(handler: BaseHTTPRequestHandler) -> tuple[str, bytes]:
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise RuntimeError("Choose a DOCX file to upload.")

    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Invalid upload length.") from exc

    if content_length <= 0 or content_length > MAX_DOCX_BYTES:
        raise RuntimeError("The DOCX upload must be smaller than 50 MB.")

    body = handler.rfile.read(content_length)
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\n"
        b"MIME-Version: 1.0\r\n\r\n" + body
    )
    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") != "source_file":
            continue
        filename = Path(part.get_filename() or "").name
        if not filename.lower().endswith(".docx"):
            raise RuntimeError("Upload a Microsoft Word DOCX file.")
        payload = part.get_payload(decode=True) or b""
        if not payload:
            raise RuntimeError("The uploaded DOCX file is empty.")
        return filename, payload

    raise RuntimeError("Choose a DOCX file to upload.")


def parse_multipart_form(
    handler: BaseHTTPRequestHandler,
) -> tuple[dict[str, tuple[str, bytes]], dict[str, str]]:
    """Split one multipart/form-data POST into file parts and plain text fields.

    Returns (files, fields): files maps field name to (filename, payload);
    fields maps field name to its decoded text value. A field is treated as a
    file if the part declares a filename, matching how <input type="file">
    and plain <input>/hidden fields differ in the multipart body.
    """
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise RuntimeError("Choose files to upload.")

    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise RuntimeError("Invalid upload length.") from exc

    if content_length <= 0 or content_length > MAX_DOCX_BYTES:
        raise RuntimeError("The upload must be smaller than 50 MB.")

    body = handler.rfile.read(content_length)
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\n"
        b"MIME-Version: 1.0\r\n\r\n" + body
    )
    files: dict[str, tuple[str, bytes]] = {}
    fields: dict[str, str] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        if filename is not None:
            payload = part.get_payload(decode=True) or b""
            files[name] = (Path(filename).name, payload)
        else:
            payload = part.get_payload(decode=True) or b""
            fields[name] = payload.decode("utf-8", errors="replace")
    return files, fields


def uploaded_docx_field(
    files: dict[str, tuple[str, bytes]],
    field_name: str,
    required: bool = True,
) -> bytes:
    """Pull one named .docx file out of a parse_multipart_form() files dict."""
    entry = files.get(field_name)
    if not entry or not entry[1]:
        if required:
            raise RuntimeError(f"Upload a file for {field_name.replace('_', ' ')} before comparing.")
        return b""
    filename, payload = entry
    if not filename.lower().endswith(".docx"):
        raise RuntimeError(f"{field_name.replace('_', ' ').title()} must be a .docx file.")
    return payload


def extract_docx_text(payload: bytes) -> str:
    # Two ingestion-safety checks, verified against real crafted input before
    # this was added: (1) ZipInfo.file_size is the archive's own *declared*
    # uncompressed size, checked before ever calling .read() -- a ~0.5MB
    # zip with one deliberately-repetitive entry decompressed to 1GB+ with no
    # cap in place, so this must happen before decompression, not after.
    # (2) a real Word document.xml never has a DOCTYPE -- it's pure content,
    # no DTD -- so rejecting one outright (rather than trying to selectively
    # allow "safe" entities) closes the XML entity-expansion ("billion
    # laughs") path with no false positives on legitimate files. A 605-byte
    # crafted payload with 6 nested entity levels expanded to 300,000 chars
    # in 10ms with no guard in place; ElementTree.fromstring() does not
    # protect against this on its own.
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise RuntimeError("The DOCX document's content is too large to process.")
            document_xml = archive.read(info)
    except (KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError("The uploaded file is not a readable DOCX document.") from exc

    # Anywhere in the document, not just at the very start: an anchored
    # "^\s*(<?xml...?>)?<!DOCTYPE" check is bypassable by putting anything
    # else first -- a comment or processing instruction (`<!--x--><!DOCTYPE
    # ...>`) slides straight past it and reaches ElementTree.fromstring()
    # below with the DOCTYPE (and any entities it declares) intact,
    # reopening the exact billion-laughs path the check above exists to
    # close. A real Word document.xml never contains either token under any
    # circumstances, so a plain substring search has no false positives.
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", document_xml, re.IGNORECASE):
        raise RuntimeError("The uploaded file is not a readable DOCX document.")

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise RuntimeError("The DOCX document text could not be read.") from exc

    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraphs: list[str] = []
    for paragraph_node in root.iter(f"{{{namespace}}}p"):
        parts: list[str] = []
        for node in paragraph_node.iter():
            if node.tag == f"{{{namespace}}}t":
                parts.append(node.text or "")
            elif node.tag == f"{{{namespace}}}tab":
                parts.append("\t")
            elif node.tag in {f"{{{namespace}}}br", f"{{{namespace}}}cr"}:
                parts.append("\n")
        paragraphs.append("".join(parts).rstrip())

    text = "\n".join(paragraphs).strip()
    if not text:
        raise RuntimeError("No transcription text was found in the DOCX document.")
    return text
