"""coverage gate report: print line coverage per workspace and fail below a threshold.

Reads the istanbul style `coverage-summary.json` files written by `npm run test:coverage`:
either one merged file at `<root>/coverage/` (files are grouped by workspace) or one per
workspace at `<root>/<workspace>/coverage/`.

    python -m scripts.gates.coverage_report --root app --min 80
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SUMMARY = "coverage-summary.json"
EXIT_BELOW_THRESHOLD = 1
EXIT_NO_DATA = 2


def find_summaries(root: Path) -> list[Path]:
    merged = root / "coverage" / SUMMARY
    if merged.is_file():
        return [merged]
    return sorted(root.glob(f"*/coverage/{SUMMARY}"))


def _lines(entry: dict) -> tuple[int, int]:
    return int(entry["lines"]["covered"]), int(entry["lines"]["total"])


def workspace_totals(summary: Path, root: Path) -> dict[str, tuple[int, int]]:
    """Covered and total lines per workspace in one summary file."""
    data = json.loads(summary.read_text())
    totals: dict[str, list[int]] = {}
    if summary.parent == root / "coverage":
        for name, entry in data.items():
            if name == "total":
                continue
            relative = (
                os.path.relpath(os.path.realpath(name), root.resolve())
                if os.path.isabs(name)
                else name
            )
            workspace = Path(relative).parts[0]
            covered, total = _lines(entry)
            acc = totals.setdefault(workspace, [0, 0])
            acc[0] += covered
            acc[1] += total
    else:
        totals[summary.parent.parent.name] = list(_lines(data["total"]))
    return {name: (acc[0], acc[1]) for name, acc in totals.items()}


def render(totals: dict[str, tuple[int, int]], minimum: float) -> tuple[str, bool]:
    covered = sum(c for c, _ in totals.values())
    total = sum(t for _, t in totals.values())
    pct = 100.0 * covered / total if total else 0.0
    ok = total > 0 and pct >= minimum
    rows = [("workspace", "lines", "covered/total")]
    rows += [(n, f"{_pct(c, t):.2f}%", f"{c}/{t}") for n, (c, t) in sorted(totals.items())]
    rows.append(("TOTAL", f"{pct:.2f}%", f"{covered}/{total}"))
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    lines = [f"{r[0]:<{widths[0]}}  {r[1]:>{widths[1]}}  {r[2]:>{widths[2]}}" for r in rows]
    verdict = "ok" if ok else "BELOW THRESHOLD"
    lines.append(f"required: {minimum:g}% lines -> {verdict}")
    return "\n".join(lines), ok


def _pct(covered: int, total: int) -> float:
    return 100.0 * covered / total if total else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=Path("app"), help="app directory")
    parser.add_argument("--min", type=float, default=80.0, dest="minimum", help="minimum lines %%")
    parser.add_argument(
        "--require-workspaces",
        default="",
        help="comma separated workspaces that must appear in the report",
    )
    args = parser.parse_args(argv)

    summaries = find_summaries(args.root)
    if not summaries:
        sys.stderr.write(f"no {SUMMARY} found under {args.root}; did test:coverage run?\n")
        return EXIT_NO_DATA
    totals: dict[str, tuple[int, int]] = {}
    for summary in summaries:
        totals.update(workspace_totals(summary, args.root))

    missing = [w for w in filter(None, args.require_workspaces.split(",")) if w not in totals]
    if missing:
        sys.stderr.write(f"no coverage data for workspace(s): {', '.join(missing)}\n")
        return EXIT_NO_DATA

    table, ok = render(totals, args.minimum)
    print(table)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Line coverage\n\n```\n{table}\n```\n")
    return 0 if ok else EXIT_BELOW_THRESHOLD


if __name__ == "__main__":
    sys.exit(main())
