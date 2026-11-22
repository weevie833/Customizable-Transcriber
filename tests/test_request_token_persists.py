"""The request token is kept in the user-data folder, so a page left open
while the app restarts can still save (before, every start made a new token
and the open page's next save failed with "missing or invalid request token")."""

import os
import stat

import app


def test_token_is_made_once_and_reused(tmp_path):
    first = app.load_request_token(tmp_path)
    assert len(first) >= 32
    assert app.load_request_token(tmp_path) == first
    mode = stat.S_IMODE(os.stat(tmp_path / app.REQUEST_TOKEN_FILE_NAME).st_mode)
    if os.name == "posix":
        assert mode == 0o600


def test_damaged_token_file_is_replaced(tmp_path):
    (tmp_path / app.REQUEST_TOKEN_FILE_NAME).write_text("short", encoding="utf-8")
    token = app.load_request_token(tmp_path)
    assert token != "short" and len(token) >= 32
    assert app.load_request_token(tmp_path) == token


def test_unwritable_folder_still_gives_a_token(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert len(app.load_request_token(blocker / "sub")) >= 32
