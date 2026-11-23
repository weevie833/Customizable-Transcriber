"""CODEX_REVIEW_2.md M-11: an update interrupted with a partial runtime and a
good backup must be recovered before any backup is rotated. Runs the real Mac
start script against a temporary runtime whose "Python" is a stub, so no
download or package install happens. The Windows script has the same logic
and is exercised by the CI windows-install job only."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "Start Customizable Transcriber (Mac).command"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or platform.machine() != "arm64",
    reason="the Mac start script only runs on Apple silicon",
)

# Base "python": `-m venv --clear DIR` makes DIR/bin/python, a stub whose pip
# install fails when FAIL_PIP is set and whose -c import check always passes.
BASE_STUB = """#!/bin/bash
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    dir="${@: -1}"
    rm -rf "$dir"; mkdir -p "$dir/bin"
    cat > "$dir/bin/python" <<'INNER'
#!/bin/bash
if [ "$2" = "pip" ]; then [ -n "$FAIL_PIP" ] && exit 1; echo new > "$(dirname "$0")/../which.txt"; exit 0; fi
exit 0
INNER
    chmod +x "$dir/bin/python"
    exit 0
fi
exit 0
"""


def _sha() -> str:
    for line in SCRIPT.read_text().splitlines():
        if line.startswith("PYTHON_SHA256="):
            return line.split('"')[1]
    raise AssertionError("PYTHON_SHA256 not found")


def _app(tmp_path: Path) -> Path:
    app = tmp_path / "App"
    app.mkdir()
    shutil.copy2(SCRIPT, app / SCRIPT.name)
    (app / "app.py").write_text("")
    (app / "requirements.lock").write_text("pkg==2\n")
    return app


def _python(runtime: Path, name: str, tag: str) -> None:
    binary = runtime / name / "bin" / "python3"
    binary.parent.mkdir(parents=True)
    binary.write_text(BASE_STUB)
    binary.chmod(0o755)
    (runtime / name / "which.txt").write_text(tag)


def _venv(runtime: Path, name: str, tag: str, lock: str = "pkg==1\n") -> None:
    venv = runtime / name / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/bash\nexit 0\n")
    (venv / "python").chmod(0o755)
    (runtime / name / "which.txt").write_text(tag)
    (runtime / name / "installed-requirements.txt").write_text(lock)


def _run(app: Path, runtime: Path, **env: str) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "CT_RUNTIME_DIR": str(runtime), "CT_INSTALL_ONLY": "1", **env}
    return subprocess.run(
        ["/bin/bash", str(app / SCRIPT.name)], env=full_env, capture_output=True, text=True, timeout=60
    )


def _interrupted_venv_update(tmp_path: Path) -> tuple[Path, Path]:
    app, runtime = _app(tmp_path), tmp_path / "Runtime"
    runtime.mkdir()
    _python(runtime, "python", "good-python")
    (runtime / "python-build.txt").write_text(_sha() + "\n")
    _venv(runtime, "venv", "partial", lock="")
    _venv(runtime, "venv-old", "good-venv")
    (runtime / "update-pending.txt").write_text("venv\n")
    return app, runtime


def test_failed_retry_after_interrupted_update_keeps_last_working_venv(tmp_path):
    app, runtime = _interrupted_venv_update(tmp_path)
    result = _run(app, runtime, FAIL_PIP="1")
    assert result.returncode == 1, result.stdout + result.stderr
    assert (runtime / "venv" / "which.txt").read_text() == "good-venv"
    assert not (runtime / "venv-old").exists()
    assert not (runtime / "update-pending.txt").exists()


def test_successful_retry_after_interrupted_update(tmp_path):
    app, runtime = _interrupted_venv_update(tmp_path)
    result = _run(app, runtime)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (runtime / "venv" / "which.txt").read_text() == "new\n"
    assert (runtime / "venv" / "installed-requirements.txt").read_text() == "pkg==2\n"
    assert not (runtime / "venv-old").exists()
    assert not (runtime / "update-pending.txt").exists()


def test_interrupted_python_update_restores_python_and_build_marker(tmp_path):
    """Interrupted after the new build marker was written: the old Python and
    its marker come back, so the next start re-downloads instead of running
    old Python under the new marker."""
    app, runtime = _app(tmp_path), tmp_path / "Runtime"
    runtime.mkdir()
    _python(runtime, "python", "partial-python")
    _python(runtime, "python-old", "good-python")
    _venv(runtime, "venv-old", "good-venv")
    (runtime / "python-build.txt").write_text(_sha() + "\n")
    (runtime / "python-build.txt.old").write_text("old-build\n")
    (runtime / "update-pending.txt").write_text("python\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text("#!/bin/bash\nexit 22\n")  # no network: the re-download fails
    (bin_dir / "curl").chmod(0o755)
    result = _run(app, runtime, PATH=f"{bin_dir}:{os.environ['PATH']}")
    assert result.returncode == 1
    assert "couldn't be downloaded" in result.stdout
    assert (runtime / "python" / "which.txt").read_text() == "good-python"
    assert (runtime / "venv" / "which.txt").read_text() == "good-venv"
    assert (runtime / "python-build.txt").read_text() == "old-build\n"
    assert not (runtime / "update-pending.txt").exists()


def test_ordinary_failed_package_update_still_restores(tmp_path):
    app, runtime = _app(tmp_path), tmp_path / "Runtime"
    runtime.mkdir()
    _python(runtime, "python", "good-python")
    (runtime / "python-build.txt").write_text(_sha() + "\n")
    _venv(runtime, "venv", "good-venv")
    result = _run(app, runtime, FAIL_PIP="1")
    assert result.returncode == 1
    assert (runtime / "venv" / "which.txt").read_text() == "good-venv"
    assert not (runtime / "update-pending.txt").exists()
