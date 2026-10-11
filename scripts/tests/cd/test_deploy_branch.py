"""Stage, promote, roll back and skip against a real (local, bare) git remote."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cd_helpers import include, sha

from scripts.cd import deploy_branch as db
from scripts.cd import deploy_state as ds

RUN_URL = "https://github.com/o/r/actions/runs/"


def git(*args: str, cwd: Path | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    path = tmp_path / "remote.git"
    git("init", "--bare", "--quiet", "--initial-branch", "main", str(path))
    return path


@pytest.fixture
def outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "github_output"
    path.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))
    return path


def artifact(tmp_path: Path, n: int, marker: str | None = None) -> Path:
    """A built app for build n; `marker` makes its files differ from other builds."""
    path = tmp_path / f"artifact-{n}"
    (path / "assets").mkdir(parents=True)
    (path / "index.html").write_text(f'<div id="root"></div> {marker or n}')
    (path / "assets" / f"app-{n}.js").write_text(f"console.log({n})")
    info = {
        "sha": sha(n),
        "short": sha(n)[:7],
        "built_at": "2026-10-11T09:00:00Z",
        "run_id": 1000 + n,
        "version": f"v0.{n}.0",
    }
    (path / "build.json").write_text(json.dumps(info))
    return path


def run_cd(*argv: str, remote: Path, includes: list[ds.Include] | None = None) -> int:
    return db.main([argv[0], "--remote", str(remote), *argv[1:]])


def common(n: int, run_id: int | None = None) -> list[str]:
    rid = run_id or 1000 + n
    return ["--sha", sha(n), "--run-id", str(rid), "--run-url", f"{RUN_URL}{rid}"]


def stage(remote: Path, tmp_path: Path, n: int, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setenv("CD_INCLUDES", json.dumps([include(10 + n, 20 + n, n).as_dict()]))
    return run_cd(
        "stage",
        *common(n),
        "--artifact",
        str(artifact(tmp_path, n)),
        "--pr",
        str(10 + n),
        "--issue",
        str(20 + n),
        remote=remote,
    )


def promote(remote: Path, n: int) -> int:
    return run_cd("promote", *common(n), remote=remote)


def rollback(remote: Path, n: int, reason: str, run_id: int | None = None) -> int:
    return run_cd(
        "rollback", *common(n, run_id), "--reason", reason, "--version", f"v0.{n}.0", remote=remote
    )


def view(remote: Path, tmp_path: Path) -> tuple[Path, ds.State]:
    dest = tmp_path / f"view-{len(list(tmp_path.glob('view-*')))}"
    git("clone", "--quiet", "--branch", "deploy", str(remote), str(dest))
    return dest, ds.parse((dest / "deploy.json").read_text())


def build_of(root: Path, name: str) -> str | None:
    path = root / name / "build.json"
    return json.loads(path.read_text())["sha"] if path.exists() else None


def tree(root: Path, name: str) -> dict[str, str]:
    base = root / name
    if not base.exists():
        return {}
    return {str(p.relative_to(base)): p.read_text() for p in sorted(base.rglob("*")) if p.is_file()}


def layout(root: Path) -> set[str]:
    return {p.name for p in root.iterdir() if p.name != ".git"}


class TestStage:
    def test_creates_the_orphan_branch_on_first_use(self, remote, tmp_path, monkeypatch) -> None:
        assert stage(remote, tmp_path, 1, monkeypatch) == 0
        root, state = view(remote, tmp_path)
        assert layout(root) == {"staging", "deploy.json"}
        assert build_of(root, "staging") == sha(1)
        assert state["staging"]["status"] == "deployed"
        assert state["staging"]["pr"] == 11 and state["staging"]["issue"] == 21
        assert state["staging"]["includes"] == [{"pr": 11, "issue": 21, "sha": sha(1)}]
        assert state["prod"] is None
        assert git("rev-list", "--count", "deploy", cwd=root).strip() == "1"

    def test_commits_as_the_actions_bot(self, remote, tmp_path, monkeypatch) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        root, _ = view(remote, tmp_path)
        author = git("log", "-1", "--format=%an <%ae>", cwd=root).strip()
        assert author == f"{db.BOT_NAME} <{db.BOT_EMAIL}>"

    def test_replaces_staging_completely(self, remote, tmp_path, monkeypatch) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        stage(remote, tmp_path, 2, monkeypatch)
        root, state = view(remote, tmp_path)
        assert build_of(root, "staging") == sha(2)
        assert sorted(tree(root, "staging")) == ["assets/app-2.js", "build.json", "index.html"]
        assert state["history"][-1]["action"] == "stage"

    def test_refuses_an_artifact_that_is_another_build(self, remote, tmp_path) -> None:
        wrong = artifact(tmp_path, 7)
        code = run_cd("stage", *common(8), "--artifact", str(wrong), remote=remote)
        assert code == 1
        assert not git("ls-remote", "--heads", str(remote)).strip()  # nothing was pushed

    def test_refuses_an_artifact_with_a_symlink(self, remote, tmp_path) -> None:
        art = artifact(tmp_path, 1)
        (art / "assets" / "leak.js").symlink_to("/etc/hosts")
        assert run_cd("stage", *common(1), "--artifact", str(art), remote=remote) == 1

    def test_refuses_an_artifact_without_build_json_or_index(self, remote, tmp_path) -> None:
        art = artifact(tmp_path, 1)
        (art / "build.json").unlink()
        assert run_cd("stage", *common(1), "--artifact", str(art), remote=remote) == 1
        art = artifact(tmp_path, 2)
        (art / "index.html").unlink()
        assert run_cd("stage", *common(2), "--artifact", str(art), remote=remote) == 1


class TestPromote:
    def test_copies_staging_to_prod(self, remote, tmp_path, monkeypatch, outputs) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        assert promote(remote, 1) == 0
        root, state = view(remote, tmp_path)
        assert layout(root) == {"staging", "prod", "deploy.json"}
        assert tree(root, "prod") == tree(root, "staging")
        assert state["prod"]["sha"] == sha(1) and state["prod"]["gates"] == ["smoke", "soak"]
        assert state["staging"]["status"] == "promoted"
        assert "tag=" + state["prod"]["tag"] in outputs.read_text()
        assert state["prod"]["tag"].startswith("prod/") and state["prod"]["tag"].endswith(
            sha(1)[:7]
        )

    def test_keeps_the_previous_prod_for_rollback(self, remote, tmp_path, monkeypatch) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        promote(remote, 1)
        stage(remote, tmp_path, 2, monkeypatch)
        promote(remote, 2)
        root, state = view(remote, tmp_path)
        assert build_of(root, "prod") == sha(2)
        assert build_of(root, "prod-prev") == sha(1)
        assert state["previous_prod"]["sha"] == sha(1)

    def test_a_second_promote_of_the_same_sha_changes_nothing(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        promote(remote, 1)
        stage(remote, tmp_path, 2, monkeypatch)
        promote(remote, 2)
        head = git("rev-parse", "deploy", cwd=remote).strip()
        assert promote(remote, 2) == 0
        assert git("rev-parse", "deploy", cwd=remote).strip() == head  # no commit at all
        root, _ = view(remote, tmp_path)
        assert build_of(root, "prod-prev") == sha(1)  # not overwritten with build 2

    def test_refuses_a_sha_that_is_not_staged(self, remote, tmp_path, monkeypatch) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        assert promote(remote, 2) == 1
        _, state = view(remote, tmp_path)
        assert state["prod"] is None


class TestRollback:
    def release_one(self, remote, tmp_path, monkeypatch) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        promote(remote, 1)

    def test_smoke_failure_puts_the_last_good_build_back_on_staging(
        self, remote, tmp_path, monkeypatch, outputs
    ) -> None:
        self.release_one(remote, tmp_path, monkeypatch)
        stage(remote, tmp_path, 2, monkeypatch)
        assert rollback(remote, 2, "smoke") == 0
        root, state = view(remote, tmp_path)
        assert build_of(root, "staging") == sha(1) and build_of(root, "prod") == sha(1)
        assert tree(root, "staging") == tree(root, "prod")
        assert not (root / "prod-prev").exists()
        assert state["staging"]["status"] == "rolled-back"
        assert state["prod"]["sha"] == sha(1) and state["prod"]["tag"].endswith(sha(1)[:7])
        assert [h["action"] for h in state["history"][-2:]] == ["fail", "rollback"]
        text = outputs.read_text()
        assert "prod_overwritten=false" in text and f"restored_sha={sha(1)}" in text

    def test_soak_failure_is_the_same_and_prod_is_untouched(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        self.release_one(remote, tmp_path, monkeypatch)
        before, _ = view(remote, tmp_path)
        prod_before = tree(before, "prod")
        stage(remote, tmp_path, 2, monkeypatch)
        assert rollback(remote, 2, "soak") == 0
        root, _ = view(remote, tmp_path)
        assert tree(root, "prod") == prod_before and tree(root, "staging") == prod_before

    def test_stage_failure_after_the_push_is_rolled_back_too(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        self.release_one(remote, tmp_path, monkeypatch)
        stage(remote, tmp_path, 2, monkeypatch)  # pushed, then the pages wait failed
        assert rollback(remote, 2, "stage") == 0
        root, state = view(remote, tmp_path)
        assert build_of(root, "staging") == sha(1)
        assert state["history"][-1]["reason"] == "stage"

    def test_stage_failure_before_the_push_still_restores(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        self.release_one(remote, tmp_path, monkeypatch)
        assert rollback(remote, 2, "stage") == 0
        root, _ = view(remote, tmp_path)
        assert build_of(root, "staging") == sha(1)

    def test_promote_failure_after_prod_was_overwritten_restores_prod_from_previous(
        self, remote, tmp_path, monkeypatch, outputs
    ) -> None:
        self.release_one(remote, tmp_path, monkeypatch)
        stage(remote, tmp_path, 2, monkeypatch)
        promote(remote, 2)
        assert build_of(view(remote, tmp_path)[0], "prod") == sha(2)
        outputs.write_text("")
        assert rollback(remote, 2, "promote") == 0
        root, state = view(remote, tmp_path)
        assert layout(root) == {"staging", "prod", "deploy.json"}  # prod-prev is gone
        assert build_of(root, "prod") == sha(1) and build_of(root, "staging") == sha(1)
        assert tree(root, "prod") == tree(root, "staging")
        assert state["prod"]["sha"] == sha(1) and state["previous_prod"] is None
        assert "prod_overwritten=true" in outputs.read_text()
        assert [(h["action"], h["env"]) for h in state["history"][-3:]] == [
            ("fail", "prod"),
            ("rollback", "prod"),
            ("rollback", "staging"),
        ]
        assert sha(2)[:7] not in state["prod"]["tag"]

    def test_the_first_release_failing_leaves_an_empty_site_state(
        self, remote, tmp_path, monkeypatch, outputs
    ) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        assert rollback(remote, 1, "smoke") == 0
        root, state = view(remote, tmp_path)
        assert layout(root) == {"deploy.json"}
        assert state["staging"] is None and state["prod"] is None
        assert "restored_sha=\n" in outputs.read_text()

    def test_the_first_promotion_failing_removes_prod_again(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        self.release_one(remote, tmp_path, monkeypatch)
        assert rollback(remote, 1, "promote") == 0
        root, state = view(remote, tmp_path)
        assert layout(root) == {"deploy.json"}
        assert state["prod"] is None

    def test_a_rolled_back_deploy_branch_can_release_again(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        self.release_one(remote, tmp_path, monkeypatch)
        stage(remote, tmp_path, 2, monkeypatch)
        rollback(remote, 2, "smoke")
        stage(remote, tmp_path, 3, monkeypatch)
        assert promote(remote, 3) == 0
        root, state = view(remote, tmp_path)
        assert build_of(root, "prod") == sha(3) and build_of(root, "prod-prev") == sha(1)
        assert state["previous_prod"]["sha"] == sha(1)


class TestSkip:
    def test_records_a_superseded_run(self, remote, tmp_path, monkeypatch, outputs) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        assert (
            run_cd("skip", *common(1), "--reason", "superseded by a newer run", remote=remote) == 0
        )
        root, state = view(remote, tmp_path)
        assert state["staging"]["status"] == "superseded"
        assert state["history"][-1]["action"] == "skip"
        assert build_of(root, "staging") == sha(1)  # the tree is untouched
        assert "promoted=false" in outputs.read_text()

    def test_reports_a_promotion_that_was_cancelled_after_its_push(
        self, remote, tmp_path, monkeypatch, outputs
    ) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        promote(remote, 1)
        outputs.write_text("")
        run_cd("skip", *common(1), "--reason", "superseded", remote=remote)
        text = outputs.read_text()
        assert "promoted=true" in text and "tag=prod/" in text


class TestPushRaces:
    def test_a_lost_race_starts_over_from_a_fresh_clone(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        calls = {"n": 0}

        def mutate(root: Path, state: ds.State) -> ds.State:
            calls["n"] += 1
            if calls["n"] == 1:  # someone else pushes between our clone and our push
                other = tmp_path / "other"
                git("clone", "--quiet", "--branch", "deploy", str(remote), str(other))
                (other / "note.txt").write_text("from another writer")
                git("add", "-A", cwd=other)
                git(
                    "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qm", "other", cwd=other
                )
                git("push", "--quiet", "origin", "HEAD:deploy", cwd=other)
            (root / "ours.txt").write_text("ours")
            return state

        # the state is unchanged, so only ours.txt makes this a commit
        sleeps: list[float] = []
        db.update(str(remote), mutate, "ours", sleep=sleeps.append)
        root, _ = view(remote, tmp_path)
        assert calls["n"] == 2 and len(sleeps) == 1
        assert (root / "note.txt").exists() and (root / "ours.txt").exists()
        assert (root / "staging" / "build.json").exists()

    def test_gives_up_with_the_push_error_after_the_last_attempt(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        hook = remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'no pushes today' >&2\nexit 1\n")
        hook.chmod(0o755)
        with pytest.raises(db.GitError, match="after 3 attempts"):
            db.update(
                str(remote),
                lambda root, state: ds.skip(
                    state,
                    subject=ds.Subject(sha(1)),
                    run_url="u",
                    reason="x",
                    now="2026-10-11T09:00:00Z",
                ),
                "m",
                attempts=3,
                sleep=lambda _s: None,
            )

    def test_two_writers_one_stage_one_skip_both_survive(
        self, remote, tmp_path, monkeypatch
    ) -> None:
        stage(remote, tmp_path, 1, monkeypatch)
        pushed = {"done": False}
        real = db.commit_and_push

        def racing(dest: Path, message: str) -> None:
            if not pushed["done"]:  # a rival skip lands just before our push
                pushed["done"] = True
                run_cd("skip", *common(1), "--reason", "rival", remote=remote)
            real(dest, message)

        monkeypatch.setattr(db, "commit_and_push", racing)
        monkeypatch.setattr(db.time, "sleep", lambda _s: None)
        assert stage(remote, tmp_path, 2, monkeypatch) == 0
        _, state = view(remote, tmp_path)
        actions = [(h["action"], h["sha"]) for h in state["history"]]
        assert ("skip", sha(1)) in actions and ("stage", sha(2)) in actions
        assert ds.validate(state) == []
