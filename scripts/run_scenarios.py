"""Create the scenario inputs: owner-authored issues and the stale-test PR.

This is the only scripted step. It files the work; the pipeline does the rest.
Usage: python scripts/run_scenarios.py [--only a,b,c,d,d-maintenance] [--dry-run]
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO = "stevengonsalvez/foundry-autonomous-sdlc"
ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "scenarios"
FILES = {
    "a": "a-feature.md",
    "b": "b-vague.md",
    "c": "c-not-suitable.md",
    "d": "d-bug.md",
    "d-maintenance": "d-maintenance.md",
}
OLD_HEADING, NEW_HEADING = "Track your parcel", "Track a parcel"

Gh = Callable[[list[str], str | None], str]


def gh(args: list[str], stdin: str | None = None) -> str:
    done = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {done.stderr.strip()[:300]}")
    return done.stdout


def parse(path: Path) -> tuple[dict[str, str], str]:
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", path.read_text(), re.DOTALL)
    if not match:
        raise ValueError(f"{path.name}: missing front matter")
    meta = dict(line.split(": ", 1) for line in match.group(1).splitlines())
    return meta, match.group(2).strip()


def create_issue(meta: dict[str, str], body: str, run: Gh) -> int:
    payload = {
        "title": meta["title"],
        "body": f"{body}\n\n<!-- scenario: {meta['scenario']} -->",
        "labels": [f"type:{meta['type']}"],
    }
    out = run(["api", f"repos/{REPO}/issues", "--input", "-"], json.dumps(payload))
    return int(json.loads(out)["number"])


def find_heading_file() -> str:
    hits = subprocess.run(
        ["git", "grep", "-l", OLD_HEADING, "--", "app/web/src", ":!*.test.*", ":!*.spec.*"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.split()
    if len(hits) != 1:
        raise RuntimeError(f"expected exactly one source file with the heading, got {hits}")
    return hits[0]


def create_stale_test_pr(meta: dict[str, str], body: str, run: Gh, path: str) -> int:
    branch = meta["branch"]
    main_sha = run(["api", f"repos/{REPO}/git/ref/heads/main", "--jq", ".object.sha"]).strip()
    run(["api", f"repos/{REPO}/git/refs", "--input", "-"],
        json.dumps({"ref": f"refs/heads/{branch}", "sha": main_sha}))
    current = json.loads(run(["api", f"repos/{REPO}/contents/{path}?ref=main"]))
    text = base64.b64decode(current["content"]).decode()
    if OLD_HEADING not in text:
        raise RuntimeError(f"{path} does not contain the heading on main")
    run(["api", "-X", "PUT", f"repos/{REPO}/contents/{path}", "--input", "-"], json.dumps({
        "message": "feat(web): update home page heading copy",
        "content": base64.b64encode(text.replace(OLD_HEADING, NEW_HEADING).encode()).decode(),
        "sha": current["sha"], "branch": branch,
    }))
    pr = json.loads(run(["api", f"repos/{REPO}/pulls", "--input", "-"], json.dumps({
        "title": meta["pr_title"], "head": branch, "base": "main", "body": body,
    })))
    run(["api", f"repos/{REPO}/issues/{pr['number']}/labels", "--input", "-"],
        json.dumps({"labels": ["maintenance:test-repair"]}))
    return int(pr["number"])


def run_scenarios(only: list[str], run: Gh = gh, dry_run: bool = False) -> dict[str, int]:
    created: dict[str, int] = {}
    for key in only:
        meta, body = parse(SCENARIOS / FILES[key])
        if dry_run:
            print(f"[dry-run] {key}: {meta.get('title') or meta.get('pr_title')}")
            continue
        if key == "d-maintenance":
            created[key] = create_stale_test_pr(meta, body, run, find_heading_file())
        else:
            created[key] = create_issue(meta, body, run)
        print(f"{key}: #{created[key]}")
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=",".join(FILES))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    keys = [k.strip() for k in args.only.split(",") if k.strip()]
    unknown = [k for k in keys if k not in FILES]
    if unknown:
        parser.error(f"unknown scenario(s): {unknown}")
    run_scenarios(keys, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
