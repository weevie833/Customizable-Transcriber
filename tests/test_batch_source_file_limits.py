"""Regression tests for the remainder of reviews/CODEX_REVIEW.md finding M-1 /
reviews/HUMAN_DECISIONS.md: batch source-file discovery had no per-file size
ceiling and no symlink rejection before sending a file's bytes to an AI
provider. validate_batch_source_file() now rejects both cases with a clear
RuntimeError -- which run_batch()'s existing per-image try/except turns
into one failed image, not a fatal batch abort."""

from __future__ import annotations

import pytest

from customizable_transcriber import core


def test_oversized_file_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MAX_BATCH_IMAGE_BYTES", 10)
    big_file = tmp_path / "page_001.jpg"
    big_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)

    with pytest.raises(RuntimeError, match="over the"):
        core.validate_batch_source_file(big_file, tmp_path)


def test_file_within_limit_is_allowed(tmp_path):
    small_file = tmp_path / "page_001.jpg"
    small_file.write_bytes(b"\xff\xd8\xff\xe0")

    core.validate_batch_source_file(small_file, tmp_path)  # must not raise


def test_symlinked_file_is_rejected(tmp_path):
    real_file = tmp_path / "outside" / "real.jpg"
    real_file.parent.mkdir()
    real_file.write_bytes(b"\xff\xd8\xff\xe0")

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    linked_file = source_folder / "page_001.jpg"
    try:
        linked_file.symlink_to(real_file)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")

    with pytest.raises(RuntimeError, match="symlink"):
        core.validate_batch_source_file(linked_file, source_folder)


def test_file_reached_through_a_symlinked_directory_is_rejected(tmp_path):
    real_dir = tmp_path / "outside_dir"
    real_dir.mkdir()
    (real_dir / "page_001.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    source_folder = tmp_path / "source"
    source_folder.mkdir()
    linked_dir = source_folder / "aliased_subdir"
    try:
        linked_dir.symlink_to(real_dir)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")

    # Reached via the symlinked directory, not a symlinked file itself --
    # Path.is_symlink() on the file alone would miss this.
    file_via_symlink = linked_dir / "page_001.jpg"
    with pytest.raises(RuntimeError, match="symlink"):
        core.validate_batch_source_file(file_via_symlink, source_folder)


def test_ordinary_file_is_not_flagged_as_a_symlink(tmp_path):
    source_folder = tmp_path / "source"
    nested = source_folder / "subdir"
    nested.mkdir(parents=True)
    real_file = nested / "page_001.jpg"
    real_file.write_bytes(b"\xff\xd8\xff\xe0")

    core.validate_batch_source_file(real_file, source_folder)  # must not raise
