"""Generic OOXML package-level XML for a minimal single-document .docx --
the two fixed parts every DOCX needs regardless of what content goes in
word/document.xml. Shared by app.py's main transcription writer and
test_mode/report_docx.py's comparison-report writer; split out (rather than
defined once and imported by whichever module happened to need it second)
specifically so neither of those two writer modules has to import the
other -- both are leaf consumers of this one instead."""

from __future__ import annotations


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
