"""The built app as an artifact: stamp it with build.json, or break it on purpose for a drill.

    python -m scripts.cd.artifact stamp --dist app/web/dist-pages --sha ... --short ... \
        --run-id 1 --version v0.4.0 [--fault smoke]
    python -m scripts.cd.artifact fault-smoke --dist app/web/dist-pages

The fault is applied to the BUILT files, never to the source, and `stamp --fault smoke` records it
in build.json so the run page is honest about why the smoke test failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ghcli import fail, utc_now

HEADING = "Track a parcel"
BROKEN_HEADING = "Track a parc3l"


class ArtifactError(RuntimeError):
    pass


def stamp(
    dist: Path,
    *,
    sha: str,
    short: str,
    run_id: int,
    version: str,
    built_at: str,
    fault: str | None = None,
) -> dict[str, object]:
    if not (dist / "index.html").is_file():
        raise ArtifactError(f"{dist} has no index.html: not a built app")
    info: dict[str, object] = {
        "sha": sha,
        "short": short,
        "built_at": built_at,
        "run_id": run_id,
        "version": version,
    }
    if fault:
        info["fault"] = fault
    (dist / "build.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def inject_smoke_fault(dist: Path) -> int:
    """Rewrite the home heading in the built JavaScript. Returns how many files were changed."""
    changed = 0
    for js in sorted((dist / "assets").glob("*.js")):
        text = js.read_text(encoding="utf-8")
        if HEADING in text:
            js.write_text(text.replace(HEADING, BROKEN_HEADING), encoding="utf-8")
            changed += 1
    if not changed:
        raise ArtifactError(f"found no built script containing {HEADING!r} under {dist}/assets")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    stamp_cmd = sub.add_parser("stamp")
    stamp_cmd.add_argument("--sha", required=True)
    stamp_cmd.add_argument("--short", required=True)
    stamp_cmd.add_argument("--run-id", type=int, required=True)
    stamp_cmd.add_argument("--version", required=True)
    stamp_cmd.add_argument("--fault", choices=("none", "smoke"), default="none")
    fault_cmd = sub.add_parser("fault-smoke")
    for cmd in (stamp_cmd, fault_cmd):
        cmd.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "stamp":
            fault = None if args.fault == "none" else args.fault
            info = stamp(
                args.dist,
                sha=args.sha,
                short=args.short,
                run_id=args.run_id,
                version=args.version,
                built_at=utc_now(),
                fault=fault,
            )
            print(json.dumps(info))
        else:
            print(f"fault injected into {inject_smoke_fault(args.dist)} built script(s)")
    except ArtifactError as err:
        return fail(str(err))
    return 0


if __name__ == "__main__":
    sys.exit(main())
