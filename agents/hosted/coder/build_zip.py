"""
Build the sdlc-coder deployment zip: main.py and requirements.txt at the root plus the
sdlc_agents package (remote_build installs requirements.txt; see decision D9).

The zip is byte-for-byte deterministic (sorted entries, fixed timestamps), so an unchanged
tree has an unchanged sha256 and the service reuses the existing agent version.

Usage: python agents/hosted/coder/build_zip.py [out.zip]
"""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1] / "sdlc_agents"
ROOT_FILES = ("main.py", "requirements.txt")
_EPOCH = (1980, 1, 1, 0, 0, 0)


def _entries() -> list[tuple[str, Path]]:
    entries = [(name, HERE / name) for name in ROOT_FILES]
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            entries.append((f"sdlc_agents/{path.relative_to(PACKAGE).as_posix()}", path))
    return entries


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in _entries():
            info = zipfile.ZipInfo(arcname, date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            # Regular-file bit: without it the service reports "No Python dependency manifest found".
            info.external_attr = 0o100644 << 16
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def main(argv: list[str]) -> int:
    data = build_zip()
    if argv:
        Path(argv[0]).write_bytes(data)
    print(f"sdlc-coder zip: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
