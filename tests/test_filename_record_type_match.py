from xls_conversion.ai_parser import check_record_type_filename_match


def test_nati_filename_matches_civil_birth():
    name = "napoli-stella-nati-v1-transcription-20260920-163529-776103.docx"
    assert check_record_type_filename_match("civil_birth", name) is None


def test_mismatch_warning_uses_dropdown_name():
    warning = check_record_type_filename_match("civil_birth", "napoli-stella-morti-v1.docx")
    assert warning and '"Civil Nati"' in warning["message"]
