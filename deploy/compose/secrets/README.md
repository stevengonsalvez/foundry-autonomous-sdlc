# Secrets for the compose stack

Two files live here. Both are gitignored (only this README is tracked) and must be mode `600`, owned by
the uid in `.env` `FACTORY_UID`.

| File | Used by | Content |
|---|---|---|
| `github_pat.txt` | worker-foreman, coder | GitHub token for the target repository |
| `agy_cli_token.txt` | coder only | agy (Antigravity CLI) OAuth token file |

Compose mounts them at `/run/secrets/github_pat` and `/run/secrets/agy_cli_token`. They are never baked
into an image or passed as environment variables. Inside the coder, root reads them and copies the agy
token per job, and per prompt-agent call, into a HOME owned by `agyuser` (mode 600); `agyuser`
(uid 61000) cannot read `/run/secrets`. worker-foreman never mounts the agy token.

## GitHub token: `github_pat.txt`

1. GitHub, Settings, Developer settings, Fine-grained tokens, Generate new token.
2. Resource owner: the repository owner. Repository access: only the target repository
   (`factory/factory.yaml` `repositories`, default `stevengonsalvez/foundry-autonomous-sdlc`).
3. Repository permissions: Contents read and write, Pull requests read and write, Issues read and write,
   Metadata read. Add Actions read and Checks read so the gates can see CI.
4. Save it with no trailing newline, then lock it down:

```bash
cd deploy/compose
umask 077
printf '%s' 'github_pat_...' > secrets/github_pat.txt
chmod 600 secrets/github_pat.txt
```

## agy token: `agy_cli_token.txt`

agy has no headless login. Log in once, interactively, on a dev machine you trust, then copy the token
file it writes.

```bash
agy                                # interactive; complete the Google sign-in in the browser, then quit
ls -l ~/.gemini/antigravity-cli/antigravity-oauth-token
install -m 600 ~/.gemini/antigravity-cli/antigravity-oauth-token deploy/compose/secrets/agy_cli_token.txt
```

Notes:

- The token is a personal Google OAuth token. Using it for automation is an accepted risk (Antigravity
  Terms, section 6): see `docs/factory-runbook.md`, "ToS note".
- Refreshed tokens are not written back (each job gets a fresh copy). When the token expires, jobs
  escalate with "authentication required": log in again on the dev machine and copy the file again.
  No restart is needed: the services read the file on every use.
- Copying from another host: `scp -p` keeps the mode; check it with `stat -c '%a %u' secrets/*.txt`.

## Fake mode

`FACTORY_MODE=fake` (the smoke test) never reads either secret, but compose still needs both files to
exist. `smoke.sh` writes dummy files in a temp directory and points `GITHUB_PAT_HOST_FILE` and
`AGY_TOKEN_HOST_FILE` at them, so real files here are never touched.
