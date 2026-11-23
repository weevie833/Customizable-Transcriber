"""Regression tests for the DOCX ingestion guards in app.py's
extract_docx_text() -- see docs/DESIGN.md's "Security hardening history"
section on the DOCTYPE-bypass finding this closes."""

from __future__ import annotations

import io
import zipfile

import pytest

import app as ctapp

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_bytes(document_xml: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _valid_document_xml(text: str = "Hello world") -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{NS}"><w:body><w:p><w:r>'
        f"<w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    ).encode()


def test_legitimate_docx_extracts_cleanly():
    text = ctapp.extract_docx_text(_docx_bytes(_valid_document_xml("Hello world")))
    assert "Hello world" in text


def test_doctype_at_start_is_rejected():
    payload = b'<!DOCTYPE foo [<!ENTITY x "boom">]><root/>'
    with pytest.raises(RuntimeError):
        ctapp.extract_docx_text(_docx_bytes(payload))


def test_doctype_after_comment_is_rejected():
    """The exact bypass reported: an anchored "starts with DOCTYPE" regex
    lets a comment slide the DOCTYPE past the check. Confirmed exploitable
    before the fix; must be rejected now."""
    payload = b'<!--comment--><!DOCTYPE foo [<!ENTITY x "boom">]><root/>'
    with pytest.raises(RuntimeError):
        ctapp.extract_docx_text(_docx_bytes(payload))


def test_doctype_after_processing_instruction_is_rejected():
    payload = b'<?xml-stylesheet type="text/xsl" href="x.xsl"?><!DOCTYPE foo><root/>'
    with pytest.raises(RuntimeError):
        ctapp.extract_docx_text(_docx_bytes(payload))


def test_bare_entity_without_doctype_wrapper_is_rejected():
    payload = b'<?xml version="1.0"?><root><!ENTITY x "boom"><a/></root>'
    with pytest.raises(RuntimeError):
        ctapp.extract_docx_text(_docx_bytes(payload))


def test_billion_laughs_style_payload_is_rejected_not_expanded():
    """End-to-end version of the same guard: a small nested-entity payload
    that would otherwise blow up in memory/CPU during ElementTree.fromstring()."""
    payload = (
        b'<?xml version="1.0"?>'
        b"<!DOCTYPE lolz [\n"
        b'<!ENTITY lol0 "lol">\n'
        b'<!ENTITY lol1 "&lol0;&lol0;&lol0;&lol0;&lol0;&lol0;&lol0;&lol0;&lol0;&lol0;">\n'
        b'<!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">\n'
        b"]>\n"
        b"<root>&lol2;</root>"
    )
    with pytest.raises(RuntimeError):
        ctapp.extract_docx_text(_docx_bytes(payload))


def test_missing_document_xml_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("not-a-real-part.xml", b"<root/>")
    with pytest.raises(RuntimeError):
        ctapp.extract_docx_text(buffer.getvalue())


def test_not_a_zip_file_is_rejected():
    with pytest.raises(RuntimeError):
        ctapp.extract_docx_text(b"this is not a zip file at all")


def test_oversized_declared_xml_is_rejected_before_decompression():
    """A small zip whose entry *declares* (via ZipInfo.file_size) a payload
    larger than MAX_DOCX_XML_BYTES must be rejected without ever calling
    .read() on it -- the size check has to run on the declared size, not
    the actual decompressed bytes, or a highly-compressible repetitive
    payload defeats it."""
    huge_repetitive_xml = _valid_document_xml("x" * 1024) * (ctapp.MAX_DOCX_XML_BYTES // 1024 + 1)
    with pytest.raises(RuntimeError):
        ctapp.extract_docx_text(_docx_bytes(huge_repetitive_xml))


# reviews/CODEX_REVIEW_8.md M-9: the no-DTD rule holds whatever the XML
# encoding, not only for ASCII-compatible bytes.
import io as _io
import zipfile as _zipfile

import pytest as _pytest

from http_utils import extract_docx_text as _extract

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(xml_bytes: bytes) -> bytes:
    buffer = _io.BytesIO()
    with _zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml_bytes)
    return buffer.getvalue()


_BODY = f'<w:document xmlns:w="{_W}"><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>'


@_pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-16-be"])
def test_ordinary_document_reads_in_each_encoding(encoding):
    declared = "UTF-16" if encoding.startswith("utf-16") else "UTF-8"
    xml = f'<?xml version="1.0" encoding="{declared}"?>{_BODY}'
    data = xml.encode(encoding)
    if encoding in ("utf-16-le", "utf-16-be"):
        data = ("﻿" + xml).encode(encoding)
    assert "Hello" in _extract(_docx(data))


def test_utf16_doctype_is_rejected_at_the_parser():
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        f'<w:document xmlns:w="{_W}"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>'
    )
    data = xml.encode("utf-16")
    assert b"<!DOCTYPE" not in data  # the byte search alone can't see it
    with _pytest.raises(RuntimeError, match="not a readable DOCX"):
        _extract(_docx(data))
