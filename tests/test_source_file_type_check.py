"""Preflight Check's file-type check (source_file_type_check() in run_support.py)."""

from pathlib import Path

from run_support import source_file_type_check


def _touch(folder: Path, *names: str) -> None:
    for name in names:
        (folder / name).write_bytes(b"x")


def test_no_folder_blocks():
    assert source_file_type_check(None, "jpeg")["ok"] is False


def test_missing_folder_blocks(tmp_path):
    assert source_file_type_check(tmp_path / "gone", "jpeg")["ok"] is False


def test_wrong_type_selected_blocks_and_names_the_right_one(tmp_path):
    _touch(tmp_path, "a.PNG", "b.png", "c.png")
    result = source_file_type_check(tmp_path, "jpeg")
    assert result["ok"] is False
    assert result["message"] == (
        "The source folder has no JPEG files, but it has 3 PNG files. Change File type to PNG."
    )


def test_empty_folder_blocks(tmp_path):
    _touch(tmp_path, "notes.txt")
    result = source_file_type_check(tmp_path, "png")
    assert result == {"ok": False, "message": "The source folder has no JPEG or PNG files."}


def test_matching_type_passes_quietly(tmp_path):
    _touch(tmp_path, "a.jpg", "b.JPEG")
    assert source_file_type_check(tmp_path, "jpeg") == {"ok": True, "message": ""}


def test_mixed_folder_passes_with_warning(tmp_path):
    _touch(tmp_path, "a.jpg", "b.png", "c.png")
    result = source_file_type_check(tmp_path, "png")
    assert result["ok"] is True
    assert result["message"] == "The source folder also has 1 JPEG file. Only the 2 PNG files will be transcribed."
