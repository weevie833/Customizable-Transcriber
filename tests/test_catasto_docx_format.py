"""Catasto Onciario transcripts in Word: groups spaced 12 pt after instead of
separated by empty paragraphs (a household's lines stay together), labels in
bold, the blank lines restored when the DOCX is read back, and the Translate
tool translating such a page line for line."""

import re
import zipfile

from http_utils import extract_docx_text
from run_support import write_docx
from transcript_translation import (
    TranslationOptions,
    _entry_payload,
    assemble,
    build_plan,
    build_translation_prompt,
)

TEXT = """# Transcription Output


--- START OF RECORD: Lappano_007.png ---

Italian Transcription:

Ant.o Bafaro brac.te, anni 28.
Gius.e fllo brac.te an: 24.

= Testa di Ant.o — 1.

abita in Casa propria =

--- START OF RECORD: Lappano_008.png —

Italian Transcription:

D. O. M.
"""


def _paragraphs(path):
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode()
    body = xml.split("</w:tbl>", 1)[-1]  # after the header box
    out = []
    for p in re.findall(r"<w:p>.*?</w:p>", body, re.S):
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        after = re.search(r'w:after="(\d+)"', p).group(1)
        out.append((text, after, "<w:b />" in p or "<w:b/>" in p))
    return out


def test_catasto_docx_spaces_groups_and_bolds_labels(tmp_path):
    path = tmp_path / "c.docx"
    write_docx(path, TEXT, native_language="Italian", record_type="catasto_onciario", model="m")
    paras = _paragraphs(path)
    body = [p for p in paras if p[0]]
    assert len(body) == len(paras) - 1  # only the spacer after the header box is empty
    by_text = {text: (after, bold) for text, after, bold in body}
    assert by_text["--- START OF RECORD: Lappano_007.png ---"] == ("240", True)
    assert by_text["--- START OF RECORD: Lappano_008.png —"][1] is True  # autocorrected ending
    assert by_text["Italian Transcription:"] == ("240", True)
    assert by_text["Ant.o Bafaro brac.te, anni 28."] == ("0", False)  # household lines run on
    assert by_text["Gius.e fllo brac.te an: 24."] == ("240", False)
    assert by_text["abita in Casa propria ="][1] is False


def test_catasto_docx_reads_back_with_its_blank_lines(tmp_path):
    path = tmp_path / "c.docx"
    write_docx(path, TEXT, native_language="Italian", record_type="catasto_onciario", model="m")
    text = extract_docx_text(path.read_bytes())
    assert "Italian Transcription:\n\nAnt.o Bafaro brac.te, anni 28.\nGius.e fllo brac.te an: 24.\n\n= Testa" in text


def test_other_record_types_keep_empty_paragraphs_and_bold_labels(tmp_path):
    path = tmp_path / "b.docx"
    write_docx(path, TEXT, native_language="Latin", record_type="battesimi", model="m")
    paras = _paragraphs(path)
    assert ("", "0", False) in paras
    assert all(after == "0" for _, after, _ in paras)
    assert ("Italian Transcription:", "0", True) in paras
    text = extract_docx_text(path.read_bytes())
    assert "Italian Transcription:\n\nAnt.o Bafaro" in text


def test_label_with_text_on_the_same_line_is_not_bold(tmp_path):
    path = tmp_path / "b.docx"
    write_docx(path, "English Translation: On the 2nd day.\n", record_type="battesimi")
    assert _paragraphs(path) == [("English Translation: On the 2nd day.", "0", False)]


HEADER = "Record type: Catasto Onciario\nNative-language transcription: Italian\nTranslations produced: None\n\n"


def test_catasto_translation_is_line_for_line():
    plan = build_plan(HEADER + TEXT, "", ["English"], TranslationOptions())
    assert plan.line_structure
    entry = plan.entries_to_translate[0]
    payload = _entry_payload(entry, plan)
    assert payload["transcription"] == (
        "Ant.o Bafaro brac.te, anni 28.\nGius.e fllo brac.te an: 24.\n\n= Testa di Ant.o — 1.\n\nabita in Casa propria ="
    )
    prompt = build_translation_prompt(None, "Italian", ["English"], TranslationOptions(), line_structure=True)
    assert "Translate line for line" in prompt
    assert "On the Nth day" not in prompt
    assert "godparent" not in prompt

    translated = "Antonio Bafaro, day laborer, age 28\nGiuseppe, brother, day laborer, age 24\n\n= Head of Antonio — 1."
    body = assemble(plan, {entry.entry_id: {"English": translated}}, {})
    assert "English Translation:\n\nAntonio Bafaro, day laborer, age 28\nGiuseppe, brother" in body


def test_other_types_still_translate_as_one_paragraph():
    plan = build_plan(TEXT.replace("Italian Transcription", "Latin Transcription"), "", ["English"], TranslationOptions())
    assert not plan.line_structure
    assert "\n" not in _entry_payload(plan.entries_to_translate[0], plan)["transcription"]


def test_english_translation_asks_for_american_spelling():
    for line_structure in (True, False):
        prompt = build_translation_prompt(None, "Latin", ["English"], TranslationOptions(), line_structure=line_structure)
        assert "American English" in prompt
    assert "American English" not in build_translation_prompt(None, "Latin", ["Italian"], TranslationOptions())
