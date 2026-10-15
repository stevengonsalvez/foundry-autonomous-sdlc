"""
Publish UI proof screenshots to the orphan branch pr-screenshots and comment on the PR.

Used by the trusted ui-proof.yml workflow:
- Validates the artifact as untrusted data using validate_artifact.py
- Optionally validates a baseline artifact (the same states captured from the PR's base
  commit) and pixel-diffs it against the PR capture, state by state
- Commits the validated PNGs to branch pr-screenshots under pr-<number>/<head sha 8>/
  (baseline PNGs of changed states go under .../before/)
- Prunes pr-screenshots directories of PRs closed more than 14 days ago
- Upserts the single PR comment with marker <!-- ui-proof:v1 -->
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts.ui.png_diff import PngDecodeError, diff_pngs, format_pct
from scripts.ui.validate_artifact import (
    MAX_CAPTION_LEN,
    MAX_STATE_ID_LEN,
    MAX_TITLE_LEN,
    SAFE_PNG_NAME_RE,
    STATE_ID_RE,
    TEXT_RE,
    state_id_of,
    validate_artifact_dir,
)

MARKER = "<!-- ui-proof:v1 -->"
BRANCH_NAME = "pr-screenshots"
PRUNE_DAYS = 14

FIXED_ROUTES = ("home", "parcel-found", "not-found", "invalid-input")
FIXED_VIEWPORTS = ("desktop", "mobile")
ROUTE_TITLES = {
    "home": "Home",
    "parcel-found": "Parcel Found",
    "not-found": "Not Found",
    "invalid-input": "Invalid Input",
}
VIEWPORT_LABELS = {"desktop": "Desktop (1280px)", "mobile": "Mobile (390px)"}
SHORT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
STATUS_RANK = {"changed": 0, "new": 1, "unchanged": 2}


def run_cmd(cmd: list[str], *, cwd: Path | str | None = None, check: bool = True) -> str:
    res = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            f"Command {cmd} failed with exit code {res.returncode}:\n"
            f"stdout: {res.stdout}\nstderr: {res.stderr}"
        )
    return res.stdout.strip()


def resolve_pr_number(
    head_sha: str,
    repo: str,
    pull_requests_json: str | None = None,
    head_repo: str | None = None,
    head_branch: str | None = None,
) -> int | None:
    if pull_requests_json:
        try:
            data = json.loads(pull_requests_json)
            if isinstance(data, list):
                matches: list[int] = []
                for pr in data:
                    if not isinstance(pr, dict):
                        continue
                    num = pr.get("number")
                    if not isinstance(num, int):
                        continue
                    pr_head = pr.get("head") or {}
                    if pr_head.get("sha") != head_sha:
                        continue
                    pr_head_repo = (pr_head.get("repo") or {}).get("full_name")
                    pr_head_ref = pr_head.get("ref")
                    if head_repo and pr_head_repo and pr_head_repo != head_repo:
                        continue
                    if head_branch and pr_head_ref and pr_head_ref != head_branch:
                        continue
                    matches.append(num)
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    return None
        except Exception:
            pass

    # Fallback to GitHub API: pick only the PR whose head.repo.full_name and head.ref match the run
    try:
        out = run_cmd(
            ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/commits/{head_sha}/pulls"],
            check=False,
        )
        if out:
            pages = json.loads(out)
            pulls: list[Any] = []
            if isinstance(pages, list):
                for item in pages:
                    if isinstance(item, list):
                        pulls.extend(item)
                    elif isinstance(item, dict):
                        pulls.append(item)

            matches = []
            for pr in pulls:
                if not isinstance(pr, dict):
                    continue
                num = pr.get("number")
                if not isinstance(num, int):
                    continue
                pr_head = pr.get("head") or {}
                if pr_head.get("sha") != head_sha:
                    continue
                pr_head_repo = (pr_head.get("repo") or {}).get("full_name")
                pr_head_ref = pr_head.get("ref")
                if head_repo and pr_head_repo and pr_head_repo != head_repo:
                    continue
                if head_branch and pr_head_ref and pr_head_ref != head_branch:
                    continue
                matches.append(num)
            if len(matches) == 1:
                return matches[0]
    except Exception:
        pass

    return None


def _clean_items(screenshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-check manifest entries before they reach a PR comment (defence in depth).

    Entries that fail are dropped; unsafe title/caption text degrades to the state id/empty.
    """
    clean: list[dict[str, Any]] = []
    for item in screenshots:
        route = item.get("route")
        viewport = item.get("viewport")
        filename = item.get("filename")
        if route not in FIXED_ROUTES or viewport not in FIXED_VIEWPORTS:
            continue
        if not isinstance(filename, str) or not SAFE_PNG_NAME_RE.fullmatch(filename):
            continue
        if "state" in item:
            state = item["state"]
            if (
                not isinstance(state, str)
                or len(state) > MAX_STATE_ID_LEN
                or not STATE_ID_RE.fullmatch(state)
            ):
                continue
        else:
            state = state_id_of(item)
            if state is None:
                continue
        title = item.get("title")
        if not (
            isinstance(title, str) and 0 < len(title) <= MAX_TITLE_LEN and TEXT_RE.fullmatch(title)
        ):
            title = ROUTE_TITLES.get(route, state) if "state" not in item else state
        caption = item.get("caption")
        if not (
            isinstance(caption, str)
            and 0 < len(caption) <= MAX_CAPTION_LEN
            and TEXT_RE.fullmatch(caption)
        ):
            caption = ""
        clean.append(
            {
                "state": state,
                "route": route,
                "viewport": viewport,
                "filename": filename,
                "title": title,
                "caption": caption,
                "sha256": item.get("sha256"),
            }
        )
    return clean


def compare_screenshots(
    after_items: list[dict[str, Any]],
    after_dir: str | Path,
    base_items: list[dict[str, Any]],
    base_dir: str | Path,
) -> list[dict[str, Any]]:
    """Pixel-compare each state against the baseline capture.

    Returns one entry per state, ordered changed, new, unchanged (capture order within a
    group). Identical sha256 skips decoding; an undecodable pair reads as changed with an
    unknown percentage rather than as unchanged.
    """
    after_dir, base_dir = Path(after_dir), Path(base_dir)
    base_index = {(i["state"], i["viewport"]): i for i in _clean_items(base_items)}

    states: dict[str, dict[str, Any]] = {}
    for item in _clean_items(after_items):
        entry = states.setdefault(
            item["state"],
            {
                "state": item["state"],
                "title": item["title"],
                "caption": item["caption"],
                "route": item["route"],
                "viewports": {},
            },
        )
        base = base_index.get((item["state"], item["viewport"]))
        view: dict[str, Any] = {
            "after": item["filename"],
            "before": base["filename"] if base else None,
            "pct": None,
            "changed": True,
        }
        if base is not None:
            if base.get("sha256") and base.get("sha256") == item.get("sha256"):
                view.update(pct=0.0, changed=False)
            else:
                try:
                    diff = diff_pngs(
                        (base_dir / base["filename"]).read_bytes(),
                        (after_dir / item["filename"]).read_bytes(),
                    )
                    view.update(pct=diff.pct, changed=diff.changed)
                except (PngDecodeError, OSError):
                    pass
        entry["viewports"][item["viewport"]] = view

    for entry in states.values():
        views = entry["viewports"].values()
        if all(v["before"] is None for v in views):
            entry["status"] = "new"
        elif any(v["changed"] for v in views):
            entry["status"] = "changed"
        else:
            entry["status"] = "unchanged"
    return sorted(states.values(), key=lambda e: STATUS_RANK[e["status"]])


def _flat_report(screenshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for item in _clean_items(screenshots):
        entry = states.setdefault(
            item["state"],
            {
                "state": item["state"],
                "title": item["title"],
                "caption": item["caption"],
                "route": item["route"],
                "status": "plain",
                "viewports": {},
            },
        )
        entry["viewports"][item["viewport"]] = {
            "after": item["filename"],
            "before": None,
            "pct": None,
            "changed": False,
        }
    return list(states.values())


def _img(url: str, alt: str, width: int) -> str:
    return f'<img src="{url}" alt="{html.escape(alt, quote=True)}" width="{width}" />'


def format_pr_comment(
    repo: str,
    pr_number: int,
    head_sha: str,
    manifest_sha256: str,
    screenshots: list[dict[str, Any]],
    report: list[dict[str, Any]] | None = None,
    skipped: list[str] | None = None,
    base_sha: str | None = None,
) -> str:
    """Render the single upserted UI proof comment.

    With a report (baseline available) changed states come first with before/after
    side by side and the percentage of pixels that moved; unchanged states are collapsed.
    Without one the comment lists this PR's captures only.
    """
    head_short = head_sha[:8]
    base_url = f"https://raw.githubusercontent.com/{repo}/{BRANCH_NAME}/pr-{pr_number}/{head_short}"
    skipped_ids = [
        sid
        for sid in (skipped or [])
        if isinstance(sid, str) and len(sid) <= MAX_STATE_ID_LEN and STATE_ID_RE.fullmatch(sid)
    ]

    have_baseline = report is not None
    states = report if report is not None else _flat_report(screenshots)
    capture_count = sum(len(s["viewports"]) for s in states)

    lines = [
        MARKER,
        f"### UI Screenshots for `{head_short}`",
        "",
        f"- Head commit: `{head_sha}`",
    ]
    if have_baseline:
        shown_base = base_sha if base_sha and SHORT_SHA_RE.fullmatch(base_sha) else None
        lines.append(
            "- Baseline: `main`" + (f" at `{shown_base[:8]}`" if shown_base else "")
            + " (same states, same renderer)"
        )
    lines += [
        f"- Manifest SHA-256: `{manifest_sha256}`",
        f"- Storage: [`{BRANCH_NAME}`](https://github.com/{repo}/tree/{BRANCH_NAME}/pr-{pr_number}/{head_short})",
        "",
    ]

    if have_baseline:
        changed = [s for s in states if s["status"] in ("changed", "new")]
        unchanged = [s for s in states if s["status"] == "unchanged"]
        lines += [f"### What this PR changed ({len(changed)} of {len(states)} states)", ""]
        if not changed:
            lines += ["No visual changes in any captured state.", ""]
        for s in changed:
            lines += _changed_block(s, base_url)
        if unchanged:
            lines += [
                "<details>",
                f"<summary><b>Unchanged states ({len(unchanged)})</b></summary>",
                "",
                "| State | Desktop (1280px) | Mobile (390px) |",
                "|---|---|---|",
            ]
            for s in unchanged:
                cells = []
                for vp, width in (("desktop", 200), ("mobile", 100)):
                    view = s["viewports"].get(vp)
                    cells.append(
                        _img(f"{base_url}/{view['after']}", f"{s['title']} {vp}", width)
                        if view
                        else "-"
                    )
                lines.append(f"| **{html.escape(s['title'])}** | {cells[0]} | {cells[1]} |")
            lines += ["", "</details>", ""]
    else:
        lines += [
            "_No baseline available (main could not be captured), showing this PR only._",
            "",
            "<details open>",
            f"<summary><b>Screenshots ({capture_count} captures)</b></summary>",
            "",
            "| State | Desktop (1280px) | Mobile (390px) |",
            "|---|---|---|",
        ]
        for s in states:
            cells = []
            for vp, width in (("desktop", 320), ("mobile", 160)):
                view = s["viewports"].get(vp)
                cells.append(
                    _img(f"{base_url}/{view['after']}", f"{s['title']} {vp}", width)
                    if view
                    else "-"
                )
            lines.append(f"| **{html.escape(s['title'])}** | {cells[0]} | {cells[1]} |")
        lines += ["", "</details>", ""]

    if skipped_ids:
        lines += [
            "<details>",
            f"<summary>Not present in this build ({len(skipped_ids)})</summary>",
            "",
            *[f"- `{sid}`" for sid in skipped_ids],
            "",
            "</details>",
            "",
        ]
    lines.append("*(Advisory UI proof captured deterministically via Playwright)*")
    return "\n".join(lines)


def _changed_block(state: dict[str, Any], base_url: str) -> list[str]:
    title = html.escape(state["title"])
    if state["status"] == "new":
        summary = "**New state**, not present on main"
    else:
        parts = []
        for vp in FIXED_VIEWPORTS:
            view = state["viewports"].get(vp)
            if view and view["changed"]:
                parts.append(f"{vp} {format_pct(view['pct'])}")
        summary = "pixels changed: " + ", ".join(parts) if parts else "changed"
    out = [f"#### {title} (`{state['state']}`)", "", summary]
    if state["caption"]:
        out += ["", f"> {html.escape(state['caption'])}"]
    out += ["", "| | Before (main) | After (this PR) |", "|---|---|---|"]
    for vp, width in (("desktop", 320), ("mobile", 160)):
        view = state["viewports"].get(vp)
        if not view:
            continue
        before = (
            _img(f"{base_url}/before/{view['before']}", f"{state['title']} {vp} before", width)
            if view["before"]
            else "_not on main_"
        )
        after = _img(f"{base_url}/{view['after']}", f"{state['title']} {vp} after", width)
        out.append(f"| **{vp.capitalize()}** | {before} | {after} |")
    out.append("")
    return out


def post_or_update_comment(repo: str, pr_number: int, body: str) -> None:
    comments_raw = run_cmd(
        [
            "gh",
            "api",
            f"repos/{repo}/issues/{pr_number}/comments",
            "--paginate",
            "--slurp",
        ]
    )
    pages = json.loads(comments_raw) if comments_raw else []
    comments: list[dict[str, Any]] = []
    if isinstance(pages, list):
        for p in pages:
            if isinstance(p, list):
                comments.extend(p)
            elif isinstance(p, dict):
                comments.append(p)

    existing_id = None
    for comment in comments:
        user = comment.get("user") or {}
        user_login = user.get("login")
        c_body = comment.get("body", "")
        if user_login == "github-actions[bot]" and c_body.startswith(MARKER):
            existing_id = comment.get("id")
            break

    if existing_id is not None:
        run_cmd(
            [
                "gh",
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/comments/{existing_id}",
                "-f",
                f"body={body}",
            ]
        )
        print(f"Updated existing UI proof comment {existing_id} on PR #{pr_number}")
    else:
        run_cmd(
            [
                "gh",
                "api",
                "-X",
                "POST",
                f"repos/{repo}/issues/{pr_number}/comments",
                "-f",
                f"body={body}",
            ]
        )
        print(f"Posted new UI proof comment on PR #{pr_number}")


def prune_old_prs(worktree_dir: Path, repo: str) -> list[int]:
    pruned: list[int] = []
    now = datetime.datetime.now(datetime.UTC)

    for item in worktree_dir.iterdir():
        if not item.is_dir() or not item.name.startswith("pr-"):
            continue
        pr_num_str = item.name[3:]
        if not pr_num_str.isdigit():
            continue
        num = int(pr_num_str)

        try:
            pr_data_raw = run_cmd(
                [
                    "gh",
                    "pr",
                    "view",
                    str(num),
                    "--repo",
                    repo,
                    "--json",
                    "state,closedAt",
                ],
                check=False,
            )
            if not pr_data_raw:
                continue
            pr_info = json.loads(pr_data_raw)
            state = pr_info.get("state")
            closed_at_str = pr_info.get("closedAt")
            if state in ("CLOSED", "MERGED") and closed_at_str:
                closed_at = datetime.datetime.fromisoformat(closed_at_str.replace("Z", "+00:00"))
                if (now - closed_at).total_seconds() > PRUNE_DAYS * 86400:
                    shutil.rmtree(item)
                    pruned.append(num)
                    print(f"Pruned stale screenshots for closed PR #{num}")
        except Exception as exc:
            print(f"Notice: Could not check status for PR #{num}: {exc}", file=sys.stderr)

    return pruned


def load_baseline(
    base_dir: str | Path | None, artifacts_dir: str | Path, screenshots: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Validate the baseline artifact and compare it with this PR's capture.

    A missing or invalid baseline never fails the proof: it just means no before/after.
    Returns (report, baseline head sha) or (None, None).
    """
    if not base_dir or not Path(base_dir).is_dir():
        return None, None
    base_res = validate_artifact_dir(base_dir)
    if not base_res.valid:
        print(
            "Notice: baseline artifact invalid, publishing without before/after:\n"
            + "\n".join(f"  - {e}" for e in base_res.errors),
            file=sys.stderr,
        )
        return None, None
    report = compare_screenshots(screenshots, artifacts_dir, base_res.screenshots, base_dir)
    base_sha = (base_res.manifest or {}).get("head_sha")
    return report, base_sha if isinstance(base_sha, str) else None


def publish(
    artifacts_dir: str | Path,
    head_sha: str,
    repo: str,
    pr_number: int | None = None,
    pull_requests_json: str | None = None,
    head_repo: str | None = None,
    head_branch: str | None = None,
    base_dir: str | Path | None = None,
) -> None:
    print(f"Validating artifacts in {artifacts_dir}...")
    res = validate_artifact_dir(artifacts_dir)
    if not res.valid:
        err_msg = "Artifact validation failed:\n" + "\n".join(f"  - {e}" for e in res.errors)
        raise RuntimeError(err_msg)

    report, base_sha = load_baseline(base_dir, artifacts_dir, res.screenshots)
    if report is not None:
        counts = {k: sum(1 for s in report if s["status"] == k) for k in STATUS_RANK}
        print(f"Baseline comparison: {counts}")

    if pr_number is None:
        pr_number = resolve_pr_number(
            head_sha=head_sha,
            repo=repo,
            pull_requests_json=pull_requests_json,
            head_repo=head_repo,
            head_branch=head_branch,
        )

    if pr_number is None:
        print(f"No open PR found for head sha {head_sha}. Nothing to publish.")
        return

    print(f"Publishing UI screenshots for PR #{pr_number} (head sha: {head_sha[:8]})...")

    work_dir = Path(tempfile.mkdtemp(dir=os.environ.get("RUNNER_TEMP")))

    published_manifest_sha256 = ""
    target_ref = f"refs/heads/{BRANCH_NAME}"

    try:
        # Initialize or clone pr-screenshots branch
        run_cmd(["git", "init"], cwd=work_dir)
        remote_url = f"https://github.com/{repo}.git"
        run_cmd(["git", "remote", "add", "origin", remote_url], cwd=work_dir)

        remote_branches = run_cmd(
            ["git", "ls-remote", "--heads", "origin", BRANCH_NAME],
            cwd=work_dir,
            check=False,
        )
        remote_heads = [
            line.split()[1]
            for line in remote_branches.splitlines()
            if len(line.split()) >= 2
        ]
        if target_ref in remote_heads:
            run_cmd(["git", "fetch", "origin", BRANCH_NAME, "--depth=1"], cwd=work_dir)
            run_cmd(["git", "checkout", BRANCH_NAME], cwd=work_dir)
        else:
            run_cmd(["git", "checkout", "--orphan", BRANCH_NAME], cwd=work_dir)

        target_dir = work_dir / f"pr-{pr_number}" / head_sha[:8]
        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy verified PNGs
        artifacts_path = Path(artifacts_dir)
        for screenshot in res.screenshots:
            fn = screenshot["filename"]
            shutil.copy2(artifacts_path / fn, target_dir / fn)

        # Baseline PNGs are only needed where the comment shows a before image
        before_dir = target_dir / "before"
        shutil.rmtree(before_dir, ignore_errors=True)
        if report is not None and base_dir:
            before_dir.mkdir(parents=True, exist_ok=True)
            for state in report:
                if state["status"] != "changed":
                    continue
                for view in state["viewports"].values():
                    if view["before"]:
                        shutil.copy2(Path(base_dir) / view["before"], before_dir / view["before"])

        # Write rebuilt manifest containing only allowlisted keys
        rebuilt_manifest = {
            "version": 1,
            "screenshots": [
                {
                    "filename": s["filename"],
                    "route": s["route"],
                    "sha256": s["sha256"],
                    "size": s["size"],
                    "viewport": s["viewport"],
                    **{k: s[k] for k in ("state", "title", "caption") if k in s},
                }
                for s in res.screenshots
            ],
        }
        skipped_states = (res.manifest or {}).get("skipped")
        if skipped_states:
            rebuilt_manifest["skipped"] = skipped_states
        manifest_bytes = (
            json.dumps(rebuilt_manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        (target_dir / "manifest.json").write_bytes(manifest_bytes)
        published_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

        # Prune old PRs closed more than 14 days ago
        pruned = prune_old_prs(work_dir, repo)

        # Configure git committer
        run_cmd(["git", "config", "user.name", "github-actions[bot]"], cwd=work_dir)
        run_cmd(
            [
                "git",
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
            ],
            cwd=work_dir,
        )

        run_cmd(["git", "add", "-A"], cwd=work_dir)
        status = run_cmd(["git", "status", "--porcelain"], cwd=work_dir)

        if status:
            msg = f"proof: UI screenshots for PR #{pr_number} at {head_sha[:8]}"
            if pruned:
                msg += f" (pruned: {', '.join(f'#{n}' for n in pruned)})"
            run_cmd(["git", "commit", "-m", msg], cwd=work_dir)

            # Push with a loop of up to 3 attempts with rebase
            for attempt in range(3):
                try:
                    pull_res = subprocess.run(
                        ["git", "pull", "--rebase", "origin", BRANCH_NAME],
                        cwd=work_dir,
                        capture_output=True,
                        text=True,
                    )
                    if pull_res.returncode != 0:
                        run_cmd(["git", "rebase", "--abort"], cwd=work_dir, check=False)
                        if target_ref in remote_heads:
                            raise RuntimeError(
                                f"git pull --rebase failed: {pull_res.stderr.strip()}"
                            )
                    run_cmd(["git", "push", "origin", BRANCH_NAME], cwd=work_dir)
                    print(f"Pushed UI screenshots to branch {BRANCH_NAME}")
                    break
                except Exception as exc:
                    run_cmd(["git", "rebase", "--abort"], cwd=work_dir, check=False)
                    if attempt == 2:
                        raise RuntimeError(
                            f"Failed to push to {BRANCH_NAME} after 3 attempts: {exc}"
                        ) from exc
                    time.sleep(1)
        else:
            print("No changes to commit on pr-screenshots branch.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    # Upsert comment on the PR
    comment_body = format_pr_comment(
        repo=repo,
        pr_number=pr_number,
        head_sha=head_sha,
        manifest_sha256=published_manifest_sha256,
        screenshots=res.screenshots,
        report=report,
        skipped=(res.manifest or {}).get("skipped"),
        base_sha=base_sha,
    )
    post_or_update_comment(repo, pr_number, comment_body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish validated UI screenshots.")
    parser.add_argument("--artifacts-dir", required=True, help="Directory of artifacts")
    parser.add_argument("--head-sha", required=True, help="Head commit sha")
    parser.add_argument("--repo", required=True, help="Repository owner/name")
    parser.add_argument("--pr-number", type=int, help="Pull request number")
    parser.add_argument("--pull-requests-json", help="JSON string of PRs from workflow event")
    parser.add_argument("--head-repo", help="Head repository full name")
    parser.add_argument("--head-branch", help="Head branch name")
    parser.add_argument(
        "--base-dir", help="Directory of the baseline artifact (same states captured from main)"
    )

    args = parser.parse_args()
    pull_requests_json = args.pull_requests_json or os.environ.get("PULL_REQUESTS_JSON")
    head_repo = args.head_repo or os.environ.get("HEAD_REPO")
    head_branch = args.head_branch or os.environ.get("HEAD_BRANCH")

    publish(
        artifacts_dir=args.artifacts_dir,
        head_sha=args.head_sha,
        repo=args.repo,
        pr_number=args.pr_number,
        pull_requests_json=pull_requests_json,
        head_repo=head_repo,
        head_branch=head_branch,
        base_dir=args.base_dir,
    )


if __name__ == "__main__":
    main()
