# PR Screenshots Post-Mortem and Pipeline Diagnosis

Post-mortem investigation into why pull request screenshots were absent prior to commit `007d2ea5`, verification of the screenshot capture and publishing pipeline, evidence from the live post-merge execution across pull requests, and an analysis of control center proof captures.

Research and documentation only: no code changes, no workflow modifications, no settings changes, and no branch merges were performed.

Date: 2026-10-14 (as of 18:15 UTC)  
Repository: `stevengonsalvez/foundry-autonomous-sdlc`  
Base commit: `007d2ea5d647a660cc991f0d7dd21741168dfcec` (origin/main, updated with sync to `a3d59db`)  
Diagnosis starting commit: `ac680df75a0040d4b7c15010ce6d27c7260f8160` (origin/main before PR 74 merged)  
Tags:
- `[VERIFIED]`: Confirmed directly with exact command and output against the repository, GitHub API, or local execution.
- `[INFERRED]`: Reasoned from verified facts, codebase logic, or GitHub Actions architectural specifications.

---

## Executive Summary

Before commit `007d2ea5` (the merge of Pull Request 74 at 16:34:29Z), pull requests displayed no screenshot comments. The root cause was that `.github/workflows/ui-proof.yml` was absent from the default branch (`main`). Because `ui-proof.yml` relies on the `workflow_run` event triggered by the completion of `CI`, GitHub Actions strictly requires the workflow file to exist on the repository default branch; without it on `main`, the workflow was never registered or scheduled.

With the merge of PR 74 as commit `007d2ea5`, the screenshot pipeline is fully operational and proven in production:
1. `[VERIFIED]` GitHub Actions workflow `UI Proof` runs automatically from `main` on `workflow_run` completion of `CI`.
2. `[VERIFIED]` The branch `origin/pr-screenshots` dynamically stores captured screenshots under `pr-<number>/<head_short>/`.
3. `[VERIFIED]` Pull Requests 61, 76, and 77 each display a live `<!-- ui-proof:v1 -->` comment posted by `github-actions[bot]` with embedded desktop (1280px) and mobile (390px) screenshots served by `raw.githubusercontent.com`. Subsequent PRs (69, 75, 78, 79, 80) similarly publish captures to `pr-screenshots`.

---

## 1. Current State (Post 007d2ea5)

Following the merge of PR 74 as commit `007d2ea5`, the screenshot pipeline fired immediately across existing open and new pull requests.

### 1.1 Live UI Proof Workflow Runs
`[VERIFIED]` The `UI Proof` workflow is active and runs from `main` upon completion of `CI`.

Command:
```bash
gh run list --workflow="UI Proof" -L 5
```
Output:
```
STATUS  TITLE     WORKFLOW  BRANCH  EVENT         ID           ELAPSED  AGE
✓       UI Proof  UI Proof  main    workflow_run  38600334489  21s      about 5 minutes ago
✓       UI Proof  UI Proof  main    workflow_run  38599858786  11s      about 8 minutes ago
✓       UI Proof  UI Proof  main    workflow_run  38599734193  38s      about 9 minutes ago
✓       UI Proof  UI Proof  main    workflow_run  38599731922  20s      about 9 minutes ago
-       UI Proof  UI Proof  main    workflow_run  38599684414  4s       about 9 minutes ago
```

Run details verified against run execution logs and proof commit timestamps:
- Run `38599731922`: Published PR 61 (head commit `8121bbc9`), committing `4c11da7` at 16:38:13Z.
- Run `38599734193`: Published PR 76 (head commit `1db251f6`), committing `6d7c025` at 16:38:32Z.
- Run `38599858786`: Logged `Artifact ui-screenshots not found; skipping.` and published nothing.
- Run `38599684414`: Skipped (run condition not met).
- Run `38600334489`: Published PR 77 (head commit `24eb07d3`), committing `c45f6c7` at 16:42:35Z.

### 1.2 Storage on pr-screenshots Branch
`[VERIFIED]` The publishing job commits and pushes validated PNG artifacts to `origin/pr-screenshots` under per-PR directories.

Command:
```bash
git log -n 4 --oneline origin/pr-screenshots
```
Output:
```
c45f6c7 proof: UI screenshots for PR #77 at 24eb07d3
6d7c025 proof: UI screenshots for PR #76 at 1db251f6
4c11da7 proof: UI screenshots for PR #61 at 8121bbc9
aedd0f0 chore(history): backfill release screenshots (v0.1.0 to v0.4.0)
```

Command:
```bash
git ls-tree origin/pr-screenshots
```
Output (as of 18:15 UTC, with subsequent PRs):
```
040000 tree 991b1b72929f0ffbab99cb24817b363a19a1a3f3	pr-61
040000 tree 45697d02f0610b55978ccca02f3d341b4b22a649	pr-69
040000 tree 780cab0a6af706e1324f92b77d1264b67f24305b	pr-75
040000 tree dd13fd60b480051b0d105645f99c43a1b8c97c00	pr-76
040000 tree ad7397bf4938cea24deaa293bc49bbb204d84430	pr-77
040000 tree 866afb969d6c0e805e32eeb2eda4cf5086236d79	pr-78
040000 tree 2b80ee41f9245b4cf45a84b8df35e6e5fc51f462	pr-79
040000 tree 69cb93455cb0eb34921c2f97d849dbafa1bc57d3	pr-80
040000 tree 893c4967279778477bacd426ce2ff22215fea7e6	releases
```

### 1.3 Verified Comments on Live PRs
`[VERIFIED]` Live comments are posted by `github-actions[bot]` on PR 61, PR 76, and PR 77 (later updated to head `d7d4b7fb` when PR 77 pushed new commits).

Command:
```bash
gh pr view 77 --json comments --jq '.comments[] | select(.body | startswith("<!-- ui-proof:v1 -->")) | .body'
```
Output:
```markdown
<!-- ui-proof:v1 -->
### UI Screenshots for `d7d4b7fb`

- Head commit: `d7d4b7fbc3bc61f6638b5339581b80677119851d`
- Manifest SHA-256: `299ec93fff4260de3465bb41f5b8e4b511460228afd1d365beb6eb06658fa706`
- Storage: [`pr-screenshots`](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/tree/pr-screenshots/pr-77/d7d4b7fb)

<details open>
<summary><b>Screenshots (8 captures)</b></summary>

| Route | Desktop (1280px) | Mobile (390px) |
|---|---|---|
| **Home** | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/d7d4b7fb/home-desktop.png" alt="home desktop" width="320" /> | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/d7d4b7fb/home-mobile.png" alt="home mobile" width="160" /> |
| **Parcel Found** | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/d7d4b7fb/parcel-found-desktop.png" alt="parcel-found desktop" width="320" /> | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/d7d4b7fb/parcel-found-mobile.png" alt="parcel-found mobile" width="160" /> |
| **Not Found** | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/d7d4b7fb/not-found-desktop.png" alt="not-found desktop" width="320" /> | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/d7d4b7fb/not-found-mobile.png" alt="not-found mobile" width="160" /> |
| **Invalid Input** | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/d7d4b7fb/invalid-input-desktop.png" alt="invalid-input desktop" width="320" /> | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/d7d4b7fb/invalid-input-mobile.png" alt="invalid-input mobile" width="160" /> |

</details>

*(Advisory UI proof captured deterministically via Playwright)*
```

*(Caveat on determinism: while Playwright captures routes systematically with animations disabled and mock API data, rendered PNG file sizes may exhibit small byte variations across environments as analyzed in Section 3).*

---

## 2. Root Cause Analysis: State at Time of Diagnosis (Before 007d2ea5)

Before commit `007d2ea5`, the repository was at commit `ac680df75a0040d4b7c15010ce6d27c7260f8160`.

### 2.1 Absence of ui-proof.yml on Default Branch
`[VERIFIED]` The GitHub Actions workflow API returned HTTP 404 because `ui-proof.yml` was absent from `main`.

Command (recorded before merge):
```bash
gh api repos/stevengonsalvez/foundry-autonomous-sdlc/actions/workflows/ui-proof.yml
```
Output:
```json
{
  "message": "Not Found",
  "documentation_url": "https://docs.github.com/rest/actions/workflows#get-a-workflow",
  "status": "404"
}
```

Command:
```bash
git show ac680df:.github/workflows/ui-proof.yml
```
Output:
```
fatal: path '.github/workflows/ui-proof.yml' does not exist in 'ac680df'
```

Because GitHub Actions restricts `workflow_run` workflows to definitions residing in the default branch, the presence of `ui-proof.yml` inside feature branches (such as `stevengonsalvez/ui-tester`) was ignored by the Actions scheduler.

### 2.2 Absence of ui-screenshots in Main ci.yml
`[VERIFIED]` In `ac680df:.github/workflows/ci.yml`, the job `ui-screenshots` did not exist.

Command:
```bash
git show ac680df:.github/workflows/ci.yml | grep -n "ui-screenshots"
```
Output:
```
(exit code 1, no match)
```

Run `38597626029` on `main` executed:
```
agent-scope, gates-tests, tdd-order, test, e2e, coverage, gitleaks, agents, control-center
```
It did not contain `ui-screenshots`.

### 2.3 PR 75 Pre-Merge Run
`[INFERRED]` On PR 75 (`stevengonsalvez/esc-resolved`), run `38590271812` was created at 15:32:47Z and updated at 15:36:59Z, which predates the PR 74 merge (commit `007d2ea5` at 16:34:29Z).
A `pull_request` workflow run executes against GitHub's simulated merge ref (`refs/pull/:number/merge`). Because run `38590271812` predates the PR 74 merge, the base branch at that time lacked `ui-screenshots`, so the job was not present in that run.

### 2.4 Pre-Merge PR Comments Check
`[VERIFIED]` Prior to `007d2ea5`, neither PR 74 nor PR 76 contained screenshot comments.

Command (recorded before merge):
```bash
gh pr view 74 --json comments
gh pr view 76 --json comments
```
Output:
```json
{"comments": []}
{"comments": []}
```

---

## 3. Evidence from CI Artifacts and Local Capture

### 3.1 PR 74 CI Artifact
`[VERIFIED]` While PR 74 was open, run `38588155653` executed the `ui-screenshots` job and uploaded artifact `ui-screenshots` (ID `11905958957`, 567,986 bytes).

The artifact was downloaded into a temporary scratch directory. All 8 PNGs and `manifest.json` were confirmed:
- Resolution: All 4 desktop images were 1280x800; all 4 mobile images were 390x844.
- Content:
  - `home-desktop.png`: 114,321 bytes
  - `home-mobile.png`: 71,580 bytes
  - `parcel-found-desktop.png`: 105,981 bytes
  - `parcel-found-mobile.png`: 78,951 bytes
  - `not-found-desktop.png`: 69,424 bytes
  - `not-found-mobile.png`: 42,502 bytes
  - `invalid-input-desktop.png`: 69,832 bytes
  - `invalid-input-mobile.png`: 43,716 bytes

### 3.2 Local Execution of scripts/ui/capture.mjs
`[VERIFIED]` `capture.mjs` was executed in a throwaway clone against `@parcel/web`.

Command:
```bash
git clone --depth 1 --branch stevengonsalvez/ui-tester https://github.com/stevengonsalvez/foundry-autonomous-sdlc.git /tmp/scratch/throwaway-clone
npm --prefix /tmp/scratch/throwaway-clone/app ci
node /tmp/scratch/throwaway-clone/scripts/ui/capture.mjs --out-dir /tmp/scratch/local-capture
file /tmp/scratch/local-capture/*.png
```
Output:
```
Building app/web for screenshot capture...
vite built in 1.05s
Local web preview running at http://127.0.0.1:40925
Capturing route: home (desktop) -> Saved home-desktop.png (114305 bytes)
Capturing route: parcel-found (desktop) -> Saved parcel-found-desktop.png (105981 bytes)
Capturing route: not-found (desktop) -> Saved not-found-desktop.png (69424 bytes)
Capturing route: invalid-input (desktop) -> Saved invalid-input-desktop.png (69832 bytes)
Capturing route: home (mobile) -> Saved home-mobile.png (71585 bytes)
Capturing route: parcel-found (mobile) -> Saved parcel-found-mobile.png (78951 bytes)
Capturing route: not-found (mobile) -> Saved not-found-mobile.png (42502 bytes)
Capturing route: invalid-input (mobile) -> Saved invalid-input-mobile.png (43716 bytes)
```

Dimensions verified:
- All desktop images: 1280 x 800, 8-bit/color RGB, non-interlaced.
- All mobile images: 390 x 844, 8-bit/color RGB, non-interlaced.

Comparison across runs:
1. Local capture vs PR 74 CI artifact: 6 of 8 PNGs are byte-identical. Two differ slightly:
   - `home-desktop.png`: 114,305 bytes local vs 114,321 bytes in PR 74 CI (16-byte difference).
   - `home-mobile.png`: 71,585 bytes local vs 71,580 bytes in PR 74 CI (5-byte difference).
2. Local capture vs PR 77 CI artifact (`origin/pr-screenshots:pr-77/24eb07d3`):
   - `home-desktop.png`: 114,305 bytes in PR 77 CI (identical to local capture).
   - `home-mobile.png`: 71,585 bytes in PR 77 CI (identical to local capture).
   - All 8 screenshots match local capture byte for byte.
Conclusion: CI capture output itself varies slightly across runner runs (e.g. PR 74 CI vs PR 77 CI); cause unknown `[INFERRED]`, likely minor rendering differences in Chromium font rasterization or image compression timing.

---

## 4. Pipeline Infrastructure Audit

### 4.1 pr-screenshots Storage Branch
`[VERIFIED]` The branch `pr-screenshots` stores screenshots for both releases and pull requests.
In `scripts/ui/publish_proof.py`, function `publish`:
- Resolves the target directory as `work_dir / f"pr-{pr_number}" / head_sha[:8]`.
- Creates directories dynamically via `mkdir(parents=True, exist_ok=True)`.
- If the branch does not exist on origin, falls back to `git checkout --orphan pr-screenshots`.
Pre-existing `pr-<n>` directories are not required.

### 4.2 Workflow Permissions and Settings
`[VERIFIED]` Current repository workflow permissions:

Command:
```bash
gh api repos/stevengonsalvez/foundry-autonomous-sdlc/actions/permissions
gh api repos/stevengonsalvez/foundry-autonomous-sdlc/actions/permissions/workflow
```
Output:
```json
{
  "enabled": true,
  "allowed_actions": "all",
  "sha_pinning_required": false
}
{
  "default_workflow_permissions": "read",
  "can_approve_pull_request_reviews": false
}
```

Analysis:
1. `default_workflow_permissions: "read"`: Workflows have read-only permissions by default, but explicitly elevate scopes in their YAML definition. In `ui-proof.yml`:
   ```yaml
   permissions:
     contents: write
     pull-requests: write
   ```
   This grants `GITHUB_TOKEN` write access to push to `pr-screenshots` and write comments to pull requests via `POST /issues/{pr_number}/comments`. (Similarly, `.github/workflows/cd.yml` sets workflow default `contents: read` and defines job-level write permissions in `stage` with `contents: write`, and `promote` and `rollback` with `contents: write` and `pull-requests: write`).
2. `can_approve_pull_request_reviews: false`: This setting corresponds to the repository checkbox "Allow GitHub Actions to create and approve pull requests".
   - It restricts creating new pull requests (`POST /pulls`) and approving pull request reviews (`POST /pulls/{id}/reviews` with `APPROVE`).
   - It does NOT restrict posting comments to pull requests (`POST /issues/{id}/comments`), which is governed by `pull-requests: write`.
   - Proof: Comments posted successfully to PR 61, 76, and 77 while this setting remains `false`.
   - The checkbox does not need to be enabled for screenshot commenting, avoiding unnecessary permission expansion for `GITHUB_TOKEN`.
3. Fork protection: In `.github/workflows/ui-proof.yml`, the job `publish` contains an explicit condition:
   ```yaml
   if: >-
     github.event.workflow_run.event == 'pull_request' &&
     github.event.workflow_run.conclusion != 'cancelled' &&
     github.event.workflow_run.head_repository.full_name == github.repository
   ```
   This prevents pull requests originating from forks from triggering `ui-proof.yml` with write access.

### 4.3 Agent PR Triggers and Authentication
`[VERIFIED]` `docs/poc-findings.md` historically noted that PRs opened with GitHub Actions `GITHUB_TOKEN` do not trigger workflows.
In the actual system (`agents/sdlc_agents/runtime.py`):
```python
GITHUB_SECRET = "github-pat"
github = GitHubClient(secrets.get_secret(GITHUB_SECRET))
```
The orchestrator retrieves secret `github-pat` from Azure Key Vault. This personal access token belongs to a personal account (`stevengonsalvez`). Because PRs created by the orchestrator are authored by a personal account rather than `github-actions[bot]`, they trigger standard `pull_request` CI runs.
Evidence: PR 54 (`agent/issue-51-r1`) was authored by `stevengonsalvez` and its CI run (`38186274718`) was triggered by `event: "pull_request"`.

### 4.4 Rulesets and Branch Protection
`[VERIFIED]` Pushes to `pr-screenshots` are not blocked by branch protection or rulesets.

Command:
```bash
gh api repos/stevengonsalvez/foundry-autonomous-sdlc/rulesets
```
Output (verbatim):
```json
[
  {
    "id": 24843641,
    "name": "main-gates",
    "target": "branch",
    "source_type": "Repository",
    "source": "stevengonsalvez/foundry-autonomous-sdlc",
    "enforcement": "active",
    "node_id": "RRS_lACqUmVwb3NpdG9yec5UOMtlzgF7FXk",
    "_links": {
      "self": {
        "href": "https://api.github.com/repos/stevengonsalvez/foundry-autonomous-sdlc/rulesets/24843641"
      },
      "html": {
        "href": "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/rules/24843641"
      }
    },
    "created_at": "2026-10-10T15:19:41.128Z",
    "updated_at": "2026-10-10T15:19:41.245Z"
  }
]
```

Command:
```bash
gh api repos/stevengonsalvez/foundry-autonomous-sdlc/rulesets/24843641
```
Output (verbatim):
```json
{
  "id": 24843641,
  "name": "main-gates",
  "target": "branch",
  "source_type": "Repository",
  "source": "stevengonsalvez/foundry-autonomous-sdlc",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "exclude": [],
      "include": [
        "~DEFAULT_BRANCH"
      ]
    }
  },
  "rules": [
    {
      "type": "deletion"
    },
    {
      "type": "non_fast_forward"
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "required_reviewers": [],
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "require_review_thread_resolution": false,
        "require_extra_approval_for_unattributed_changes": true,
        "allowed_merge_methods": [
          "merge"
        ]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          {
            "context": "test",
            "integration_id": 15368
          },
          {
            "context": "coverage",
            "integration_id": 15368
          },
          {
            "context": "e2e",
            "integration_id": 15368
          },
          {
            "context": "gitleaks",
            "integration_id": 15368
          },
          {
            "context": "tdd-order",
            "integration_id": 15368
          },
          {
            "context": "agent-scope",
            "integration_id": 15368
          }
        ]
      }
    }
  ],
  "node_id": "RRS_lACqUmVwb3NpdG9yec5UOMtlzgF7FXk",
  "created_at": "2026-10-10T15:19:41.128Z",
  "updated_at": "2026-10-10T15:19:41.245Z",
  "bypass_actors": [],
  "current_user_can_bypass": "never",
  "_links": {
    "self": {
      "href": "https://api.github.com/repos/stevengonsalvez/foundry-autonomous-sdlc/rulesets/24843641"
    },
    "html": {
      "href": "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/rules/24843641"
    }
  }
}
```

Command:
```bash
gh api repos/stevengonsalvez/foundry-autonomous-sdlc/branches/pr-screenshots/protection
```
Output (verbatim):
```json
{
  "message": "Branch not protected",
  "documentation_url": "https://docs.github.com/rest/branches/branch-protection#get-branch-protection",
  "status": "404"
}
```

Finding: Ruleset `main-gates` (ID 24843641) targets only `~DEFAULT_BRANCH` (`main`) with rules `deletion`, `non_fast_forward`, `pull_request`, and `required_status_checks`. The branch `pr-screenshots` has no ruleset and returns 404 for branch protection. Pushes by `github-actions[bot]` proceed without restriction.

### 4.5 Image Serving
`[VERIFIED]` The repository is public (`"private": false`). Images committed to `pr-screenshots` are served directly by `raw.githubusercontent.com`.

Command:
```bash
curl -I -s https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-77/24eb07d3/home-desktop.png
```
Output (excerpt):
```
HTTP/2 200 
cache-control: max-age=300
content-security-policy: default-src 'none'; style-src 'unsafe-inline'; sandbox
content-type: image/png
etag: "5d05a0a9e532ff645f3402bd225bd453aa1eb74d354a3b73b59714088323d3a1"
access-control-allow-origin: *
content-length: 114305
```

Images load cleanly inside GitHub PR comments.

---

## 5. Rehearsal Plan (Reference)

*(Note: The rehearsal plan is moot in practice because the screenshot pipeline executed implicitly and succeeded across PR 61, PR 76, and PR 77 immediately upon merging commit `007d2ea5`. The procedure below is preserved for reference).*

### 5.1 Verification Checklist
1. **Actions General Permissions**: Ensure `Workflow permissions` is set to `Read repository contents and packages permissions` or `Read and write permissions`.
2. **Branch Protection**: Ensure no ruleset targets `pr-screenshots`.

### 5.2 Ordered Rehearsal Procedure
```bash
# 1. Create a test branch from latest main
git fetch origin main
git checkout -b test/ui-proof-reference origin/main

# 2. Make a trivial touch to an existing tracked file
# Note: do not create an ungitignored .tmp file as .gitignore contains no .tmp pattern.
echo "" >> README.md
git add README.md
git commit -m "docs: test ui proof reference harness"
git push -u origin test/ui-proof-reference

# 3. Create a pull request
gh pr create \
  --title "test: ui proof reference harness" \
  --body "Reference pull request to verify automated UI screenshots.

Breaking Change: No
Feature Flagged: No" \
  --head test/ui-proof-reference \
  --base main

# 4. Monitor CI run
gh run list --branch test/ui-proof-reference --workflow=CI
gh run watch <CI_RUN_ID>

# 5. Monitor trusted UI Proof run
gh run list --workflow="UI Proof" -L 3
gh run watch <UI_PROOF_RUN_ID>

# 6. Verify image storage on pr-screenshots
git fetch origin pr-screenshots
git ls-tree -r --name-only origin/pr-screenshots | grep "^pr-<PR_NUMBER>/"

# 7. Verify comment on the PR
gh pr view <PR_NUMBER> --json comments

# 8. Clean up PR and storage branch
gh pr close <PR_NUMBER> --delete-branch

# Note: gh pr close deletes the PR branch, but pr-screenshots retains the committed captures.
# To immediately remove test artifacts from pr-screenshots (without waiting for the 14-day pruning policy):
git checkout pr-screenshots
git pull origin pr-screenshots
git rm -r pr-<PR_NUMBER>
git commit -m "chore: remove rehearsal captures for PR #<PR_NUMBER>"
git push origin pr-screenshots
```

---

## 6. Control Center Screenshots: Analysis and Recommendations

### 6.1 What Exists Today
`[VERIFIED]` `apps/control-center` contains its own capture script at `apps/control-center/scripts/shots.mjs` (`package.json`: `"shots": "node scripts/shots.mjs"`).
- In commit `1e443cd` (`docs(control-center): add proof captures for all viewports and lenses`), 35 PNGs were committed to git by hand into `apps/control-center/docs/proof/` (commits `fa26cf2` and `d8f7c8b` added 6 each, bringing the total in `docs/proof` to 38 today including `before/`).
- PR 61 (`stevengonsalvez/ui-fixes`, merged as commit `4868ea8c`) regenerated and updated these static PNG files.
- In `shots.mjs`:
  - Only `board` is captured across all 4 viewport sizes (`desktop`: 1440x900, `1280`: 1280x800, `mobile`: 390x844, `360`: 360x640) across 3 lenses (Delivery, Cost, Gates) and group filters.
  - The remaining 7 views (`ticket`, `cost`, `environments`, `agents`, `escalations`, `flow`, `trail`) are captured at only 2 viewport sizes (`desktop`: 1440x900 and `360`: 360x640).
- In `.github/workflows/ci.yml`, the `control-center` job executes only `npm test` inside `apps/control-center`. It does not execute `npm run shots`.

### 6.2 Scope of Current PR Screenshot Pipeline
`[VERIFIED]` The screenshot pipeline established by PR 74 is intentionally scoped exclusively to the end-user parcel tracking web app (`app/web`):
1. `scripts/ui/capture.mjs`:
   - Builds only `@parcel/web` (`npm run build --workspace @parcel/web`).
   - Mocks routes for `/api/parcels`.
   - Captures only the 4 parcel tracking routes: `home`, `parcel-found`, `not-found`, `invalid-input`.
2. `scripts/ui/validate_artifact.py`:
   - Sets `MAX_FILE_COUNT = 16` (control center generates 38 images).
   - Validates routes with `ROUTE_RE = re.compile(r"^(home|parcel-found|not-found|invalid-input)$")`.
   - Validates viewports with `VIEWPORT_RE = re.compile(r"^(desktop|mobile)$")` and dimensions 1280x800 and 390x844 only (control center uses 1440x900, 360x640, and variable document scroll heights up to 3000px).
3. `scripts/ui/publish_proof.py`:
   - Formats a table expecting only `FIXED_ROUTES = ("home", "parcel-found", "not-found", "invalid-input")`.

### 6.3 Recommendations for Control Center PR Screenshots
*(Recommendation only; no changes made)*

To automatically capture and comment with control center screenshots on PRs modifying `apps/control-center/**`:

1. **Dedicated or Path-Filtered CI Job**:
   - Add a `control-center-screenshots` job in `ci.yml` that runs when files in `apps/control-center/**` change.
   - Run `npm run shots` using Playwright against the local fixture server, writing images to an artifact directory.
2. **Artifact Schema and Validator Adaptation**:
   - Support a manifest format identifying the app source (`"app": "control-center"`).
   - Extend `validate_artifact.py` to recognize control center route names (`board`, `ticket`, `cost`, `environments`, `agents`, `escalations`, `flow`, `trail`) and allowed dimensions (1440x900, 1280x800, 390x844, 360x640, with height bounded by `MAX_HEIGHT = 3000`).
   - Raise `MAX_FILE_COUNT` to 48 and `MAX_TOTAL_BYTES` to 40 MB.
3. **Comment Formatter**:
   - Extend `publish_proof.py` to format collapsible sections per application, storing control center images under `pr-screenshots/pr-<n>/<head_sha>/control-center/`.
