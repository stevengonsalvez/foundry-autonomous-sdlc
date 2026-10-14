# PR Screenshots Diagnosis: Why PR Screenshots Do Not Appear and How to Prove Them

Investigation into why screenshots do not appear on pull requests in repository `stevengonsalvez/foundry-autonomous-sdlc`, verification of the screenshot capture and publishing pipeline, a comprehensive blocker audit, an end-to-end rehearsal plan, and an analysis of control center proof captures.

Research and documentation only: no code changes, no workflow modifications, no settings changes, and no branch merges were performed.

Date: 2026-10-14  
Repository: `stevengonsalvez/foundry-autonomous-sdlc`  
Base commit: `ac680df75a0040d4b7c15010ce6d27c7260f8160` (origin/main)  
Tags:
- `[VERIFIED]`: Confirmed directly with exact command and output against the repository, GitHub API, or local execution.
- `[INFERRED]`: Reasoned from verified facts, codebase logic, or GitHub Actions architectural specifications.

---

## Executive Summary

Pull requests currently display no screenshot preview comments for three direct reasons:

1. `[VERIFIED]` Pull Request 74 (`stevengonsalvez/ui-tester`) is open and unmerged. The workflow file `.github/workflows/ui-proof.yml` and the script package `scripts/ui/` exist only on feature branches and do not exist on `origin/main`.
2. `[VERIFIED]` The publishing workflow `ui-proof.yml` triggers via `workflow_run` on completion of the `CI` workflow. In GitHub Actions, workflows triggered by `workflow_run` execute exclusively from the repository default branch (`main`). Because `ui-proof.yml` is absent from `main`, the GitHub Actions engine does not register or execute it (`GET /actions/workflows/ui-proof.yml` returns HTTP 404).
3. `[VERIFIED]` Pull Request 74 introduced the `ui-screenshots` job into `.github/workflows/ci.yml`. On `main` and on regular pull requests cut from `main` (such as PR 75), `ci.yml` lacks the `ui-screenshots` job entirely. On PR 74 itself, the `ui-screenshots` job did run and successfully uploaded an artifact containing 8 valid PNG images and `manifest.json`, but no comment was posted because `ui-proof.yml` could not trigger from `main`.

Once PR 74 merges to `main`, the core pipeline is structurally ready: the target storage branch `pr-screenshots` exists, GitHub Actions workflow write permissions are appropriately elevated in `ui-proof.yml`, rulesets do not block pushes to `pr-screenshots`, `raw.githubusercontent.com` serves images for this public repository, and real agent pull requests opened by the orchestrator use a personal access token (`github-pat`) which triggers standard `pull_request` workflow runs.

---

## 1. Root Cause Proof with Evidence

### 1.1 CI Runs on PR 74 vs Main and Other PRs

#### PR 74 Workflow Execution
`[VERIFIED]` PR 74 (`stevengonsalvez/ui-tester`, head commit `c8bdf53912bc4b4fc4d31ed28d3153169a20f613`) ran workflow `CI` (run ID `38588155653`).

Command:
```bash
gh run view 38588155653 --json jobs --jq '.jobs[] | {name: .name, conclusion: .conclusion}'
```
Output:
```json
{"conclusion":"success","name":"e2e"}
{"conclusion":"success","name":"gates-tests"}
{"conclusion":"success","name":"agent-scope"}
{"conclusion":"success","name":"agents"}
{"conclusion":"success","name":"tdd-order"}
{"conclusion":"success","name":"control-center"}
{"conclusion":"success","name":"gitleaks"}
{"conclusion":"success","name":"test"}
{"conclusion":"success","name":"ui-screenshots"}
{"conclusion":"success","name":"coverage"}
```

The `ui-screenshots` job succeeded.

#### Artifact Upload Verification on PR 74
`[VERIFIED]` The `ui-screenshots` job uploaded an artifact named `ui-screenshots` (ID `11905958957`, size 567,986 bytes).

Command:
```bash
gh api repos/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/38588155653/artifacts
```
Output:
```json
{
  "total_count": 1,
  "artifacts": [
    {
      "id": 11905958957,
      "name": "ui-screenshots",
      "size_in_bytes": 567986,
      "expired": false,
      "workflow_run": {
        "id": 38588155653,
        "head_branch": "stevengonsalvez/ui-tester",
        "head_sha": "c8bdf53912bc4b4fc4d31ed28d3153169a20f613"
      }
    }
  ]
}
```

#### Artifact Content and Dimensions Verification
`[VERIFIED]` The artifact was downloaded and inspected. All desktop PNG images have resolution 1280x800 and all mobile PNG images have resolution 390x844.

Commands:
```bash
gh run download 38588155653 -R stevengonsalvez/foundry-autonomous-sdlc -D /tmp/scratch/pr74-artifact
file /tmp/scratch/pr74-artifact/ui-screenshots/*.png
```
Output:
```
home-desktop.png:          PNG image data, 1280 x 800, 8-bit/color RGB, non-interlaced
home-mobile.png:           PNG image data, 390 x 844, 8-bit/color RGB, non-interlaced
invalid-input-desktop.png: PNG image data, 1280 x 800, 8-bit/color RGB, non-interlaced
invalid-input-mobile.png:  PNG image data, 390 x 844, 8-bit/color RGB, non-interlaced
not-found-desktop.png:     PNG image data, 1280 x 800, 8-bit/color RGB, non-interlaced
not-found-mobile.png:      PNG image data, 390 x 844, 8-bit/color RGB, non-interlaced
parcel-found-desktop.png:  PNG image data, 1280 x 800, 8-bit/color RGB, non-interlaced
parcel-found-mobile.png:   PNG image data, 390 x 844, 8-bit/color RGB, non-interlaced
```

Command:
```bash
cat /tmp/scratch/pr74-artifact/ui-screenshots/manifest.json
```
Output:
```json
{
  "version": 1,
  "head_sha": "c8bdf53912bc4b4fc4d31ed28d3153169a20f613",
  "screenshots": [
    {"filename": "home-desktop.png", "route": "home", "viewport": "desktop", "sha256": "9f101a4e11c5f061084ed717eeb7e932bc736b1ed0d9b70b6473ed6e07c40a8e", "size": 114321},
    {"filename": "parcel-found-desktop.png", "route": "parcel-found", "viewport": "desktop", "sha256": "2d4a7ac3272006bb5e549a2e12b3e3f7625cb9b69e8370e62e7a2b6e09946261", "size": 105981},
    {"filename": "not-found-desktop.png", "route": "not-found", "viewport": "desktop", "sha256": "85a1bc4cededc2a33733894de74eac7718e6f34e8e2ff0a3c990da451d41eeaa", "size": 69424},
    {"filename": "invalid-input-desktop.png", "route": "invalid-input", "viewport": "desktop", "sha256": "dea585c18d72606665eba6149bad429297c61f0979b0a19338d29d4b3402dac7", "size": 69832},
    {"filename": "home-mobile.png", "route": "home", "viewport": "mobile", "sha256": "520595966121bae2a207f09f99d8b34ab05a3846fca450bc2de7ff80331a8010", "size": 71580},
    {"filename": "parcel-found-mobile.png", "route": "parcel-found", "viewport": "mobile", "sha256": "9eb037bea43871852edd2a89976f0667f1666921699a4a1de40075e2a92f1849", "size": 78951},
    {"filename": "not-found-mobile.png", "route": "not-found", "viewport": "mobile", "sha256": "893678496e3a2c2113e17d23a13c882e1f554dceba5759aae44a6d10a7338ff0", "size": 42502},
    {"filename": "invalid-input-mobile.png", "route": "invalid-input", "viewport": "mobile", "sha256": "2c9322d3ddeb3560754dac9f9931861bcdc0610f1245a6f7c71b14e94d79a752", "size": 43716}
  ]
}
```

#### Comparison with Main CI Runs
`[VERIFIED]` The latest CI run on `origin/main` (commit `ac680df75a0040d4b7c15010ce6d27c7260f8160`, run ID `38597626029`) does not contain the `ui-screenshots` job.

Command:
```bash
gh run view 38597626029 --json jobs --jq '.jobs[].name'
```
Output:
```
agent-scope
gates-tests
tdd-order
test
e2e
coverage
gitleaks
agents
control-center
```

#### Comparison with Other Recent PRs
`[VERIFIED]` Pull Request 75 (`stevengonsalvez/esc-resolved`, head commit `98c1514bcda91f3f0e336ae0b299f1329f616c1a`, run ID `38590271812`) does not contain the `ui-screenshots` job because it branched from `main` without PR 74.

Command:
```bash
gh run view 38590271812 --json jobs --jq '.jobs[].name'
```
Output:
```
coverage
e2e
tdd-order
test
agents
gates-tests
agent-scope
gitleaks
control-center
```

#### Check for Existing PR Comments
`[VERIFIED]` Checking PR 74 and PR 76 reveals that neither PR received any automated comments.

Commands:
```bash
gh pr view 74 --json comments
gh pr view 76 --json comments
```
Output:
```json
{"comments": []}
{"comments": []}
```

#### Status of ui-proof.yml on Default Branch
`[VERIFIED]` The GitHub Actions workflow API returns HTTP 404 for `ui-proof.yml` because the file does not exist on `main`.

Command:
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
git show origin/main:.github/workflows/ui-proof.yml
```
Output:
```
fatal: path '.github/workflows/ui-proof.yml' does not exist in 'origin/main'
```

### 1.2 Local Execution of Capture Script

`[VERIFIED]` To verify that the capture script functions as expected on this machine without relying on external services, `scripts/ui/capture.mjs` was executed inside a throwaway git clone (isolated from all existing worktrees).

Test execution commands:
```bash
git clone --depth 1 --branch stevengonsalvez/ui-tester https://github.com/stevengonsalvez/foundry-autonomous-sdlc.git /tmp/scratch/throwaway-clone
npm --prefix /tmp/scratch/throwaway-clone/app ci
node /tmp/scratch/throwaway-clone/scripts/ui/capture.mjs --out-dir /tmp/scratch/local-capture
```

Output:
```
Building app/web for screenshot capture...

> @parcel/web@0.1.0 build
> tsc --noEmit && vite build

vite v7.3.7 building client environment for production...
transforming (1) src/main.tsx...
dist/index.html                   0.83 kB │ gzip:  0.51 kB
dist/assets/index-CSttkLXx.css   11.01 kB │ gzip:  2.99 kB
dist/assets/index-qwhroTlM.js   156.00 kB │ gzip: 50.45 kB
built in 1.05s
Local web preview running at http://127.0.0.1:40925
Setting up context for viewport desktop (1280x800)...
Capturing route: home (desktop) -> http://127.0.0.1:40925/#/
Saved home-desktop.png (114305 bytes, sha256: 5a0318dda600...)
Capturing route: parcel-found (desktop) -> http://127.0.0.1:40925/#/parcel/PK1000000001
Saved parcel-found-desktop.png (105981 bytes, sha256: 2d4a7ac32720...)
Capturing route: not-found (desktop) -> http://127.0.0.1:40925/#/parcel/PK9999999999
Saved not-found-desktop.png (69424 bytes, sha256: 85a1bc4ceded...)
Capturing route: invalid-input (desktop) -> http://127.0.0.1:40925/#/parcel/12345
Saved invalid-input-desktop.png (69832 bytes, sha256: dea585c18d72...)
Setting up context for viewport mobile (390x844)...
Capturing route: home (mobile) -> http://127.0.0.1:40925/#/
Saved home-mobile.png (71585 bytes, sha256: 365b91c3eda7...)
Capturing route: parcel-found (mobile) -> http://127.0.0.1:40925/#/parcel/PK1000000001
Saved parcel-found-mobile.png (78951 bytes, sha256: 9eb037bea438...)
Capturing route: not-found (mobile) -> http://127.0.0.1:40925/#/parcel/PK9999999999
Saved not-found-mobile.png (42502 bytes, sha256: 893678496e3a...)
Capturing route: invalid-input (mobile) -> http://127.0.0.1:40925/#/parcel/12345
Saved invalid-input-mobile.png (43716 bytes, sha256: 2c9322d3ddeb...)
Wrote manifest to /tmp/scratch/local-capture/manifest.json with 8 screenshots.
Cleaned up browser and static server.
```

Verification command:
```bash
file /tmp/scratch/local-capture/*.png
```
Output:
```
home-desktop.png:          PNG image data, 1280 x 800, 8-bit/color RGB, non-interlaced
home-mobile.png:           PNG image data, 390 x 844, 8-bit/color RGB, non-interlaced
invalid-input-desktop.png: PNG image data, 1280 x 800, 8-bit/color RGB, non-interlaced
invalid-input-mobile.png:  PNG image data, 390 x 844, 8-bit/color RGB, non-interlaced
not-found-desktop.png:     PNG image data, 1280 x 800, 8-bit/color RGB, non-interlaced
not-found-mobile.png:      PNG image data, 390 x 844, 8-bit/color RGB, non-interlaced
parcel-found-desktop.png:  PNG image data, 1280 x 800, 8-bit/color RGB, non-interlaced
parcel-found-mobile.png:   PNG image data, 390 x 844, 8-bit/color RGB, non-interlaced
```

Conclusion: `capture.mjs` runs deterministically, launches headless Chromium using Playwright, intercepts API calls, and outputs exact 1280x800 and 390x844 images along with `manifest.json`.

---

## 2. Comprehensive Blocker Analysis

This section audits every potential blocker between the current repository state and "a comment with images appears on a PR".

### 2.1 Blocker 1: Merge of Pull Request 74
- Status: `[VERIFIED]` BLOCKER.
- Details: PR 74 adds `.github/workflows/ui-proof.yml`, updates `.github/workflows/ci.yml` to include `ui-screenshots`, and adds `scripts/ui/` (`capture.mjs`, `publish_proof.py`, `validate_artifact.py`).
- Requirement: PR 74 must merge into `main`. Because GitHub Actions requires `workflow_run` workflows to reside on the default branch, no pull request will trigger `ui-proof.yml` until this merge occurs. Furthermore, `ui-proof.yml` checks out `ref: main` before executing `python -m scripts.ui.publish_proof`, meaning the Python publishing code must also be present on `main`.

### 2.2 Item 2: pr-screenshots Branch and pr-<n> Directories
- Status: `[VERIFIED]` NOT A BLOCKER.
- Verification:
  1. The branch `pr-screenshots` already exists in `origin`.
     Command:
     ```bash
     git ls-remote --heads origin pr-screenshots
     ```
     Output:
     ```
     7829285090bc0fc955ceea0a7479fc30c333a463	refs/heads/pr-screenshots
     ```
  2. The branch currently contains release screenshots under `releases/v0.1.0/` through `releases/v0.4.0/` and does not yet have `pr-<n>` directories.
  3. In `scripts/ui/publish_proof.py` (lines 198-204):
     ```python
     target_dir = work_dir / f"pr-{pr_number}" / head_sha[:8]
     target_dir.mkdir(parents=True, exist_ok=True)
     ```
     `publish_proof.py` creates `pr-<n>/<head_sha[:8]>/` dynamically using `mkdir(parents=True, exist_ok=True)`. Neither `pr-<n>` nor the commit directory needs to pre-exist. If `pr-screenshots` did not exist on the remote, line 195 has fallback logic: `git checkout --orphan pr-screenshots`.

### 2.3 Item 3: Workflow Permissions and GitHub Settings
- Status: `[VERIFIED]` READY (WITH 1 RECOMMENDED MANUAL SETTING VERIFICATION).
- Verification:
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
- Analysis:
  1. `default_workflow_permissions` is `"read"`. In GitHub Actions, when default permissions are `"read"`, workflows can request explicit elevated permissions in their YAML definition. In `ui-proof.yml`:
     ```yaml
     permissions:
       contents: write
       pull-requests: write
     ```
     This grants `GITHUB_TOKEN` write permissions to push to `pr-screenshots` and write comments to pull requests via `gh api -X POST repos/{repo}/issues/{pr_number}/comments`. (Verified by `cd.yml` which similarly elevates permissions to `contents: write`, `issues: write`, `pull-requests: write` and executes regularly).
  2. `can_approve_pull_request_reviews` is `false`. This setting controls "Allow GitHub Actions to create and approve pull requests". It blocks `POST /pulls` (creating a PR) and `POST /pulls/{id}/reviews` with `APPROVE`. It does NOT block `POST /issues/{pr_number}/comments` (adding a comment to an existing PR). However, Stevie should verify that this setting remains enabled if any workflow automation creates PRs.
  3. Fork approvals: In `ui-proof.yml`, lines 31-35 contain a strict fork guard:
     ```yaml
     if: >-
       github.event.workflow_run.event == 'pull_request' &&
       github.event.workflow_run.conclusion != 'cancelled' &&
       github.event.workflow_run.head_repository.full_name == github.repository
     ```
     Workflows from outside forks will be skipped, preventing untrusted code from triggering the publisher.

### 2.4 Item 4: Agent PRs Opened by the Orchestrator
- Status: `[VERIFIED]` NOT A BLOCKER.
- Context: `docs/poc-findings.md` noted: "Agent PRs opened with GITHUB_TOKEN do not start workflows; the owner closes and reopens to run CI and review."
- Verification of Real Implementation:
  In the production system (`agents/sdlc_agents/runtime.py` line 23, 57):
  ```python
  GITHUB_SECRET = "github-pat"
  github = GitHubClient(secrets.get_secret(GITHUB_SECRET))
  ```
  The orchestrator does NOT authenticate to GitHub using GitHub Actions `GITHUB_TOKEN`. It retrieves the Personal Access Token `github-pat` from Azure Key Vault.
  Because the PAT belongs to a real GitHub user (`stevengonsalvez`), pull requests created by the orchestrator are treated as user-created pull requests.
  Evidence from real agent PR 54 (`agent/issue-51-r1`):
  Command:
  ```bash
  gh pr view 54 --json author,headRefName
  gh run list --branch agent/issue-51-r1 --json databaseId,name,workflowName,event,conclusion
  ```
  Output:
  ```json
  {
    "author": {
      "is_bot": false,
      "login": "stevengonsalvez",
      "name": "Steven Gonsalvez"
    },
    "headRefName": "agent/issue-51-r1"
  }
  [
    {
      "conclusion": "success",
      "databaseId": 38186274718,
      "event": "pull_request",
      "name": "CI",
      "workflowName": "CI"
    }
  ]
  ```
  `[VERIFIED]` The `CI` workflow was triggered automatically by `event: "pull_request"` on PR 54 without manual close and reopen. Once `ci.yml` on `main` contains `ui-screenshots`, agent PRs will execute `ui-screenshots` and subsequent `ui-proof.yml` workflows automatically.

### 2.5 Item 5: Rulesets and Branch Protection on pr-screenshots
- Status: `[VERIFIED]` NOT A BLOCKER.
- Verification:
  Command:
  ```bash
  gh api repos/stevengonsalvez/foundry-autonomous-sdlc/rulesets
  gh api repos/stevengonsalvez/foundry-autonomous-sdlc/rulesets/24843641
  gh api repos/stevengonsalvez/foundry-autonomous-sdlc/branches/pr-screenshots/protection
  ```
  Output:
  ```json
  [
    {
      "id": 24843641,
      "name": "main-gates",
      "conditions": {
        "ref_name": {
          "include": ["~DEFAULT_BRANCH"]
        }
      }
    }
  ]
  {
    "message": "Branch not protected",
    "status": "404"
  }
  ```
- Finding: Ruleset `main-gates` (ID 24843641) targets only `~DEFAULT_BRANCH` (`main`). The branch `pr-screenshots` has no ruleset conditions and no branch protection rules. The bot (`github-actions[bot]`) pushing commits to `pr-screenshots` will not be rejected.

### 2.6 Item 6: raw.githubusercontent.com Image Serving
- Status: `[VERIFIED]` NOT A BLOCKER.
- Verification:
  The repository is public (`"private": false`).
  Test request against an existing image on `pr-screenshots`:
  ```bash
  curl -I -s https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/releases/v0.1.0/home-desktop.png
  ```
  Output:
  ```
  HTTP/2 200 
  content-type: image/png
  content-length: 112205
  access-control-allow-origin: *
  cache-control: max-age=300
  ```
- Finding: Images on `pr-screenshots` are served directly with HTTP 200 and `content-type: image/png`. When GitHub renders the markdown comment with `<img>` tags pointing to `https://raw.githubusercontent.com/{repo}/pr-screenshots/pr-{pr_number}/{head_short}/{file}`, the browser renders the images immediately.

---

## 3. End-to-End Rehearsal Plan

Once PR 74 merges to `main`, follow this ordered rehearsal plan to prove screenshot generation and comment posting end to end.

### 3.1 Pre-Flight Check of Manual Settings

Stevie must verify the following in GitHub Web Settings before running the rehearsal:

1. **Actions General Permissions** (`Settings > Actions > General`):
   - Under **Workflow permissions**, verify either:
     - `Read and write permissions`, OR
     - `Read repository contents and packages permissions` (acceptable because `ui-proof.yml` explicitly defines `contents: write` and `pull-requests: write`).
   - Check the box for: `Allow GitHub Actions to create and approve pull requests`.
2. **Rulesets** (`Settings > Rules > Rulesets`):
   - Confirm ruleset `main-gates` only includes `~DEFAULT_BRANCH`. Confirm no ruleset matches `pr-screenshots` or `refs/heads/pr-*`.

### 3.2 Ordered Rehearsal Steps and Commands

#### Step 1: Create a Throwaway Harness Branch from Updated Main
```bash
git fetch origin main
git checkout -b test/ui-proof-rehearsal origin/main

# Make a benign markdown touch that triggers CI
echo "<!-- proof rehearsal harness $(date -u +%Y%m%d%H%M%S) -->" >> docs/research/proof-rehearsal-note.tmp
git add docs/research/proof-rehearsal-note.tmp
git commit -m "test: verify ui proof screenshot pipeline on PR"
git push -u origin test/ui-proof-rehearsal
```

#### Step 2: Open a Pull Request
```bash
gh pr create \
  --title "test: proof harness verification" \
  --body "Throwaway pull request to verify automated UI screenshot capture and comment posting end to end. Breaking Change: No, Feature Flagged: No" \
  --head test/ui-proof-rehearsal \
  --base main
```
Note the returned PR number (for example, `#80`).

#### Step 3: Monitor CI Execution and Artifact Upload
```bash
# Watch the CI run triggered by the pull request
gh run list --branch test/ui-proof-rehearsal --workflow=CI
# Follow execution
gh run watch <CI_RUN_ID>

# Once CI completes, check the jobs
gh run view <CI_RUN_ID> --json jobs --jq '.jobs[] | {name: .name, conclusion: .conclusion}'
# Verify the ui-screenshots artifact was created
gh api repos/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/<CI_RUN_ID>/artifacts
```

#### Step 4: Monitor the Trusted UI Proof Workflow
```bash
# workflow_run will trigger UI Proof upon CI completion
gh run list --workflow="UI Proof" -L 3
# Follow execution
gh run watch <UI_PROOF_RUN_ID>
```

#### Step 5: Verify Storage Branch and Image Availability
```bash
# Verify commit landed on pr-screenshots
git fetch origin pr-screenshots
git log -n 1 origin/pr-screenshots --oneline

# Inspect published files for this PR
git ls-tree -r --name-only origin/pr-screenshots | grep "pr-<PR_NUMBER>"

# Verify raw.githubusercontent.com serves the newly uploaded image
HEAD_8=$(git rev-parse --short=8 HEAD)
curl -I https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/${HEAD_8}/home-desktop.png
```

#### Step 6: Verify Comment Appearance on the Pull Request
```bash
gh pr view <PR_NUMBER> --json comments --jq '.comments[] | select(.body | startswith("<!-- ui-proof:v1 -->")) | .body'
```

#### Expected Comment Content Format
The posted comment must match the following structure:
```markdown
<!-- ui-proof:v1 -->
### UI Screenshots for `<HEAD_8>`

- Head commit: `<FULL_HEAD_SHA>`
- Manifest SHA-256: `<MANIFEST_SHA256>`
- Storage: [`pr-screenshots`](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/tree/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>)

<details open>
<summary><b>Screenshots (8 captures)</b></summary>

| Route | Desktop (1280x800) | Mobile (390x844) |
|---|---|---|
| **Home** | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>/home-desktop.png" alt="home desktop" width="320" /> | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>/home-mobile.png" alt="home mobile" width="160" /> |
| **Parcel Found** | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>/parcel-found-desktop.png" alt="parcel-found desktop" width="320" /> | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>/parcel-found-mobile.png" alt="parcel-found mobile" width="160" /> |
| **Not Found** | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>/not-found-desktop.png" alt="not-found desktop" width="320" /> | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>/not-found-mobile.png" alt="not-found mobile" width="160" /> |
| **Invalid Input** | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>/invalid-input-desktop.png" alt="invalid-input desktop" width="320" /> | <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-<PR_NUMBER>/<HEAD_8>/invalid-input-mobile.png" alt="invalid-input mobile" width="160" /> |

</details>
```

#### Step 7: Clean Up Throwaway Rehearsal PR
```bash
gh pr close <PR_NUMBER> --delete-branch
```

---

## 4. Control Center Screenshots: Current State and Recommendations

### 4.1 What Exists Today
`[VERIFIED]` `apps/control-center` contains its own snapshot generator at `apps/control-center/test/shots.mjs`.
- It boots a local server against static fixture data and captures 38 PNG files across 8 views (`board`, `ticket`, `cost`, `environments`, `agents`, `escalations`, `flow`, `trail`) and 4 viewport sizes (`desktop`: 1440x900, `1280`: 1280x800, `mobile`: 390x844, `360`: 360x640).
- These captures are saved locally to `apps/control-center/docs/proof/`.
- In PR 61 (`stevengonsalvez/ui-fixes`, commit `8121bbc`), 38 PNG files were committed to git by hand into `apps/control-center/docs/proof/`.
- In `.github/workflows/ci.yml`, the `control-center` job only runs `npm test` inside `apps/control-center`. It does not execute `npm run shots`.

### 4.2 Why PR 74 Does Not Capture Control Center
`[VERIFIED]` PR 74's screenshot pipeline is dedicated solely to `@parcel/web` (`app/web`):
1. `scripts/ui/capture.mjs`:
   - Builds `@parcel/web` only (`npm run build --workspace @parcel/web`).
   - Mocks routes exclusively for `/api/parcels`.
   - Defines fixed routes `ROUTES = ["home", "parcel-found", "not-found", "invalid-input"]`.
2. `scripts/ui/validate_artifact.py`:
   - Enforces `MAX_FILE_COUNT = 16` (control center produces 38 files).
   - Enforces `ROUTE_RE = re.compile(r"^(home|parcel-found|not-found|invalid-input)$")`.
   - Enforces `VIEWPORT_RE = re.compile(r"^(desktop|mobile)$")` with strict dimension checks: 1280x800 and 390x844 only. Control center uses 1440x900 and 360x640 and scroll clipping up to 3000px height.
3. `scripts/ui/publish_proof.py`:
   - Formats a table expecting only `FIXED_ROUTES = ("home", "parcel-found", "not-found", "invalid-input")`.

### 4.3 Recommendations to Attach Control Center Screenshots to PRs
*(Architectural recommendation only; no code changes included)*

If Stevie wishes to attach control center screenshots to PRs that touch `apps/control-center` (such as PR 61):

1. **Path-Gated CI Job or Conditional Step**:
   - In `.github/workflows/ci.yml`, add an `ui-screenshots-control-center` job (or conditionally run control center capture within `ui-screenshots` if changes touch `apps/control-center/**`).
2. **Standardize Artifact Schema**:
   - Generalize `manifest.json` schema to include an `app` identifier (`"app": "web"` or `"app": "control-center"`).
   - Alternatively, output a separate artifact `ui-screenshots-control-center`.
3. **Generalize Validator Limits**:
   - Update `validate_artifact.py` to allow control center views (`board`, `ticket`, `cost`, `environments`, `agents`, `escalations`, `flow`, `trail`) and viewports (`desktop`, `1280`, `mobile`, `360`).
   - Increase `MAX_FILE_COUNT` from 16 to 48.
   - Adjust `MAX_TOTAL_BYTES` from 20 MB to 40 MB.
4. **Generalize Comment Formatter**:
   - Update `publish_proof.py` to support multi-app sections or tabbed details collapsible blocks (`<details><summary>Control Center Captures</summary>...`).
   - Store images in `pr-screenshots` under `pr-<n>/<head_sha>/control-center/`.
