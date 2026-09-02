"""Generic OOXML XML helpers shared across this app's DOCX and XLSX writers
-- the two fixed package-level parts every DOCX needs regardless of what
content goes in word/document.xml, plus a text sanitizer every writer that
embeds AI-generated or user-supplied text into hand-built XML needs. Shared
by app.py's main transcription writer, test_mode/report_docx.py's
comparison-report writer, and xls_conversion/spreadsheet_export.py's XLSX
writer; split out (rather than defined once and imported by whichever
module happened to need it second) specifically so none of those writer
modules has to import another -- all are leaf consumers of this one
instead."""

from __future__ import annotations

import re

# XML 1.0's Char production allows tab/LF/CR, U+0020-U+D7FF, U+E000-U+FFFD,
# and U+10000-U+10FFFF -- everything else (the C0 control characters other
# than tab/LF/CR, and lone UTF-16 surrogates that can end up in a Python str
# via certain decode paths) is not well-formed XML at all, full stop, no
# escaping fixes it. xml.sax.saxutils.escape() and xml.etree.ElementTree's
# own serializer both escape "<"/">"/"&" but do nothing about this -- a
# stray control byte from OCR/AI output (reproduced with a literal "\x00")
# used to sail straight through both into an XLSX cell or a DOCX paragraph,
# producing a file openpyxl/Word can't open at all. This regex matches
# everything NOT in the valid ranges, so sanitizing is "delete every match"
# rather than trying to enumerate every illegal codepoint individually.
_XML_ILLEGAL_CHARS = re.compile("[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]")


def strip_xml_illegal_chars(text: str) -> str:
    """Remove every character XML 1.0 forbids outright, before any
    tag-character escaping happens. Apply this to any text -- a worksheet
    cell, a sheet name, a DOCX paragraph, a comparison-report line -- that
    ultimately lands inside this app's hand-built XML, whether or not the
    writer also escapes "<"/">"/"&" separately."""
    return _XML_ILLEGAL_CHARS.sub("", text)


def content_types_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""


def root_rels_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
