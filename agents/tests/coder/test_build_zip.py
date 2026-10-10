"""The coder zip is flat, deterministic and self-contained."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import zipfile
from pathlib import Path

ZIP_SCRIPT = Path(__file__).resolve().parents[2] / "hosted/coder/build_zip.py"


def _module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("coder_build_zip", ZIP_SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zip_is_flat_deterministic_and_has_no_bytecode(tmp_path: Path) -> None:
    build = _module()
    data = build.build_zip()
    assert data == build.build_zip()
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert names[:2] == ["main.py", "requirements.txt"]
    assert "sdlc_agents/coder/runner.py" in names
    assert "sdlc_agents/ports.py" in names
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
    assert build.main([str(tmp_path / "out.zip")]) == 0
    assert (tmp_path / "out.zip").read_bytes() == data


def test_zip_contents_import_without_the_repo(tmp_path: Path) -> None:
    zipfile.ZipFile(io.BytesIO(_module().build_zip())).extractall(tmp_path)
    probe = "import sdlc_agents.coder.wiring, sdlc_agents.coder.runner; print('ok')"
    code = f"import sys; sys.path.insert(0, {str(tmp_path)!r}); {probe}"
    result = subprocess.run([sys.executable, "-I", "-c", code],  # noqa: S603
                            capture_output=True, text=True, cwd=tmp_path, check=False)
    assert result.stdout.strip() == "ok", result.stderr
