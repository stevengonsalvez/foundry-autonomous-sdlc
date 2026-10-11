"""
Build the sdlc-ledger deployment zip (stdlib only).

Layout at the zip root: main.py, requirements.txt and the vendored sdlc_agents package (Python
sources only; the coder runtime and caches are left out). Entries are sorted and stamped with a
fixed time, so the same sources always give a byte-identical zip and deploys can compare hashes.

Usage:
    python agents/hosted/ledger/build_zip.py [--out dist/sdlc-ledger.zip]
Prints the zip path, its size and its SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent.parent / "sdlc_agents"
ROOT_FILES = ("main.py", "requirements.txt")
EXCLUDED_DIRS = frozenset({"__pycache__", "coder"})
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
MAX_BYTES = 250 * 1024 * 1024  # platform limit for a code zip


def package_files(package: Path = PACKAGE) -> list[Path]:
    files = []
    for path in sorted(package.rglob("*.py")):
        if EXCLUDED_DIRS.intersection(path.relative_to(package).parts[:-1]):
            continue
        files.append(path)
    return files


def entries(here: Path = HERE, package: Path = PACKAGE) -> list[tuple[str, Path]]:
    """(name in zip, source path) pairs, in zip order."""
    result = [(name, here / name) for name in ROOT_FILES]
    result += [(f"sdlc_agents/{p.relative_to(package).as_posix()}", p) for p in package_files(package)]
    return result


def build(out: Path, here: Path = HERE, package: Path = PACKAGE) -> str:
    """Write the zip and return its SHA-256."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, source in entries(here, package):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            # The regular-file type bit matters: without it the service reports
            # "No Python dependency manifest found".
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, source.read_bytes())
    size = out.stat().st_size
    if size > MAX_BYTES:
        raise SystemExit(f"{out} is {size} bytes, over the {MAX_BYTES} byte limit")
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--out", type=Path, default=HERE.parent.parent / "dist" / "sdlc-ledger.zip")
    args = parser.parse_args(argv)
    digest = build(args.out)
    print(f"{args.out}  {args.out.stat().st_size} bytes  sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
