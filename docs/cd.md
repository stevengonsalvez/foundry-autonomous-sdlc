# Continuous deployment

A merged PR reaches `https://stevengonsalvez.github.io/foundry-autonomous-sdlc/staging/` by itself. It reaches prod (the site root) only after Playwright smoke on staging and a 10 minute soak with no new failure. No human step. Any failure rolls back to the previous build, flags the ticket and creates no prod tag.

```
 merge to main ─▶ CI (push) ─▶ done ─▶ cd.yml  (plan reads the 6 required checks)
                                         │
 ┌──────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌──────┐  ┌─────────┐
 │ plan │─▶│ build │─▶│ stage │─▶│ smoke │─▶│ soak │─▶│ promote │─▶ prod live + tag
 └──────┘  └───────┘  └───┬───┘  └───┬───┘  └──┬───┘  └────┬────┘
                          │ writes   │ live     │ 10 min    │ prod/ := staging/
                          ▼ staging/ ▼ staging/  ▼ probes    ▼
                      ┌────────────────────────────────────────────┐
                      │ branch `deploy`  ──▶ pages.yml ──▶ the site │
                      └────────────────────────────────────────────┘
 any job fails ─▶ rollback: staging/ := prod/, prod/ := prod-prev/ if overwritten,
                  label on the ticket, no tag
 newer merge   ─▶ waits (one pending slot); a running deploy always finishes
```

## What each job does

| Job | Does |
|-----|------|
| plan | Resolves the sha (must be on main), the merged PR, the issue (`Closes #N` in the body, else branch `agent/issue-N`), the version (`vX.Y.Z` tag on the sha, waiting up to about a minute for the orchestrator to create it, else `main-<short sha>`), and `includes` (see below). Reads `GET /commits/{sha}/check-runs` and proceeds only when the six required checks (test, coverage, e2e, gitleaks, tdd-order, agent-scope), from the Actions app, concluded `success`; an optional job such as `gates-tests` or `agents` going red does not matter. A sha that already is prod's is exempt. Skips the run (with the reason on the run page) when the checks are not green or when CI was for a sha that is no longer main HEAD. |
| build | `npm ci && npm run build:pages` at the sha, writes `build.json`, uploads artifact `site-<sha>`. |
| stage | Copies the build to `staging/` on the `deploy` branch, dispatches `pages.yml`, waits for it, then polls the live `/staging/build.json` until its sha matches (6 minute cap). Opens and closes a GitHub deployment for environment `staging`. |
| smoke | Playwright (`app/e2e/smoke/`) against the live staging URL: heading, tracking timeline of 5 events, not-found alert, `build.json` sha, no console errors, assets load from the path prefix. |
| soak | `scripts/cd/soak.py`: every 30 seconds for the soak time, fetch `index.html`, `build.json`, the JS and CSS assets, each with a unique `?cb=` query so the CDN cannot answer from its cache; the first, middle and last probe also run the Playwright smoke. A failed probe is repeated once at once (one dropped packet); a second failure fails the release. |
| promote | `prod-prev/` := `prod/`, `prod/` := `staging/` plus the previous build's assets (see below), dispatches `pages.yml`, verifies the live root `build.json`, then creates the tag `prod/<UTC yyyymmdd-HHMMSS>-<short sha>`, a `production` deployment, and comments `Released to prod: <version> (smoke and 10 minute soak passed)` on the PR, the issue and every PR and issue the build carried. Re-running it for a sha that is already prod changes nothing. |
| rollback | Runs when build, stage, smoke, soak or promote failed. Restores, publishes, verifies, flags the ticket. The job ends green; the run stays red because the failed job was red. |

## The `deploy` branch

Written only by `cd.yml` with `GITHUB_TOKEN`. Pushes retry from a fresh clone, so two writers never conflict in `deploy.json`.

```
prod/        built app live at the site root
staging/     built app on /staging/
prod-prev/   what prod/ held before the last promotion (rollback target)
deploy.json  state, schema v1
```

Every built app has `build.json` at its root: `{"sha","short","built_at","run_id","version"}` (plus `"fault":"smoke"` on a drill).

```json
{
  "version": 1,
  "staging": {"sha": "", "short": "", "version": "", "built_at": "", "deployed_at": "",
              "run_id": 0, "run_url": "", "status": "deployed", "pr": 13, "issue": 12,
              "includes": [{"pr": 13, "issue": 12, "sha": ""}]},
  "prod": {"sha": "", "short": "", "version": "", "built_at": "", "promoted_at": "",
           "run_id": 0, "run_attempt": 1, "run_url": "", "gates": ["smoke", "soak"], "pr": 13, "issue": 12,
           "tag": "prod/20261011-093005-abc1234", "includes": []},
  "previous_prod": null,
  "history": [{"at": "", "action": "stage", "env": "staging", "sha": "", "version": "",
               "run_url": "", "reason": "", "issue": null, "pr": null, "includes": []}]
}
```

- `staging.status` is one of `deployed`, `smoke-passed`, `soaking`, `promoted`, `failed`, `rolled-back`, `superseded`. The workflow writes `deployed`, `promoted` and `rolled-back` (`superseded` is accepted for old files); progress through smoke and soak is visible on the run page, not committed (two extra pushes per release for no reader).
- `history` is newest last and keeps the last 60 entries. `action` is `stage`, `promote`, `rollback`, `skip` or `fail`; `env` is `staging` or `prod`.
- `includes` lists every PR merged to main (first-parent merge commits) since the sha prod ran when this build was planned, oldest first, as `{pr, issue, sha}`. When a newer merge replaces a pending run, the newer build's `includes` still names the older ticket, so the ledger knows which tickets reach prod with it. Entries of `history` for `stage` and `promote` carry it too. With nothing in prod it holds only the build's own PR.

## The prod rule

Prod changes in one place only: `promote`, and only when `stage`, `smoke` and `soak` all succeeded for that sha. A PR can never alter its own CD: `workflow_run` workflows run from the default branch, and the scripts come from the commit the workflow was defined at. Manual runs must use main and a sha that is on main.

## Rollback

| Failed | Staging goes to | Prod goes to |
|--------|-----------------|--------------|
| stage, smoke, soak (or promote before its push) | what prod holds | unchanged |
| promote failed after its push (prod overwritten by this attempt) | what prod held before | `prod-prev/` |
| first ever release | removed | removed if it was just promoted, else unchanged |

Prod is rolled back only when the promote job of this very attempt failed and prod's own record names this run id and `run_attempt`. The run id is the same across "Re-run all jobs", so it is never enough: a rerun of a release that attempt 1 promoted, followed by a smoke flake, restores staging only and leaves prod and its tag alone.

The deploy.json history gets a `fail` and a `rollback` entry per environment, with the failing job as the reason. Then `pages.yml` runs, and the job checks that both `/staging/build.json` and the root `build.json` serve prod's sha (or are gone when nothing was ever promoted). GitHub shows a failure status on the failed deployment and a new successful one for the restored build. No prod tag is created before the live root is verified, so a failed release never has one.

The ticket (the issue, or the PR when there is no issue) gets the label `escalated:deploy-failed` and one comment per run, updated in place, with the reason and the run link. The orchestrator treats any `escalated:` label as terminal for that issue.

## Rehearse a failure

```bash
gh workflow run cd.yml -f inject_fault=smoke              # break the built heading, expect a rollback
gh workflow run cd.yml -f sha=<sha on main> -f soak_minutes=2   # a quick real release
```

`inject_fault=smoke` rewrites "Track a parcel" to "Track a parc3l" in the built JavaScript (never the source) and records `"fault":"smoke"` in `build.json`. The run summary says so. Expect: stage green, smoke red, rollback green, run red, no prod tag.

## Concurrency

The group `cd` runs one deploy at a time and never cancels the one in progress: a soak, a promote or a rollback always finishes. GitHub keeps one pending run, so a newer merge replaces a pending older one; the tickets of the replaced run reach prod through the `includes` of the next build, which lists everything merged since the sha prod runs. CI runs that are not a push to main get a group of their own, so they never take the pending slot. A CI run for a sha that is no longer main HEAD is skipped by `plan`: the newer sha has its own run.

## Cached pages and assets

Every probe (soak, live checks, the smoke specs) adds a unique `?cb=` query: the CDN ignores request no-cache headers and has served a `build.json` that was minutes old. Clients that hold an old `index.html` ask for its hashed scripts for a while after a promote or rollback, so when `prod/` is replaced it keeps the previous build's assets that the new build lacks (found by following the old `index.html` through its scripts and styles). Assets older than one generation are dropped.

## Setup

Run `python3 scripts/setup_repo.py --phase bootstrap` once so the label `escalated:deploy-failed` exists (adding a missing label to a ticket also creates it, with a default colour). Pages must be set to build from a workflow, as before.

## Known limits

- Pages is a CDN. A finished deployment is not instantly what every request sees; the live checks poll with a cache-busting query for up to 6 minutes, and a visitor may still see the old build for a short while after.
- One Pages artifact serves every path, so each deploy ships root, `/staging/`, `/dashboard/` and `/control-center/` together. A broken `pages.yml` run blocks all of them. The `pages` group keeps one pending run, so a dispatch can be replaced by a newer one; that run renders the same branch, and the live check is what decides.
- The soak is 10 minutes of synthetic probes against staging, not real traffic, and prod serves the same bytes staging did. It catches a bad deploy and a flapping CDN, not a bug only real users hit.
- `deploy` keeps every commit it ever had (a few hundred KB per release). Squash it if it ever matters.
- The site URL is derived as `https://<owner>.github.io/<repo>/`; a custom domain needs a change in `scripts/cd/plan.py`.
- The first ever release has no previous artifact to roll back to: seed `deploy/prod` by hand before the first run.
- The Actions app can push the `deploy` branch (any other writer is limited by a ruleset). Anyone who can change `cd.yml` on main can change what is served.
- A rollback does not revert main, and it flags only the newest PR (the ticket of the build it was running), not every PR the build carried.
- A CI run on main that is red for a required check still takes the pending slot, finds the checks red in `plan` and deploys nothing; the next green merge deploys everything merged since prod.
- On a personal repository the `deploy` branch cannot be locked to the Actions app: `setup_repo.py --phase protect-deploy` is refused by GitHub (HTTP 422). Anyone or anything with `contents: write` on the repository can push to `deploy`, and `pages.yml` publishes it. On an organization repository, run that phase after the first release.
