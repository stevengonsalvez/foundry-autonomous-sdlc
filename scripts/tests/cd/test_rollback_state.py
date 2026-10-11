"""deploy.json as a state machine: every way a release can fail ends on the last good build."""

from __future__ import annotations

from cd_helpers import RUN_URL, T2, promoted, release, sha, staged, subject

from scripts.cd import deploy_state as ds


def fail_run(state: ds.State, n: int, reason: str, run_id: int | None = None) -> ds.State:
    return ds.rollback(
        state,
        subject=subject(n),
        run_id=run_id or release(n).run_id,
        run_url=f"{RUN_URL}{n}",
        reason=reason,
        now=T2,
    )


def history_tail(state: ds.State, count: int) -> list[tuple[str, str, str]]:
    return [(h["action"], h["env"], h["reason"]) for h in state["history"][-count:]]


def good_prod(n: int = 1) -> ds.State:
    return promoted(ds.empty_state(), n)


class TestFailureBeforePromote:
    def test_stage_failure_restores_staging_from_prod(self) -> None:
        state = staged(good_prod(1), 2)
        after = fail_run(state, 2, "stage")
        assert after["prod"] == state["prod"]
        assert after["previous_prod"] == state["previous_prod"]
        assert after["staging"]["sha"] == sha(1)
        assert after["staging"]["status"] == "rolled-back"
        assert after["staging"]["version"] == state["prod"]["version"]
        assert history_tail(after, 2) == [
            ("fail", "staging", "job stage failed"),
            ("rollback", "staging", "stage"),
        ]
        assert after["history"][-1]["sha"] == sha(2)  # the history names the failed build
        assert ds.validate(after) == []

    def test_smoke_failure(self) -> None:
        state = staged(good_prod(1), 2)
        after = fail_run(state, 2, "smoke")
        assert after["prod"]["sha"] == sha(1) and after["staging"]["sha"] == sha(1)
        assert history_tail(after, 1) == [("rollback", "staging", "smoke")]

    def test_soak_failure(self) -> None:
        after = fail_run(staged(good_prod(1), 2), 2, "soak")
        assert after["prod"]["sha"] == sha(1) and after["staging"]["status"] == "rolled-back"
        assert history_tail(after, 2)[0] == ("fail", "staging", "job soak failed")

    def test_first_ever_release_failing_leaves_no_staging_and_no_prod(self) -> None:
        after = fail_run(staged(ds.empty_state(), 1), 1, "smoke")
        assert after["staging"] is None and after["prod"] is None
        assert after["previous_prod"] is None
        assert ds.validate(after) == []

    def test_staging_is_restored_even_when_stage_never_wrote_it(self) -> None:
        state = good_prod(1)  # the stage job failed before pushing: staging still holds prod
        after = fail_run(state, 2, "stage")
        assert after["staging"]["sha"] == sha(1) and after["prod"] == state["prod"]

    def test_a_previous_never_promoted_staging_build_is_replaced_by_prod(self) -> None:
        state = staged(staged(good_prod(1), 2), 3)
        after = fail_run(state, 3, "smoke")
        assert after["staging"]["sha"] == sha(1)


class TestPromoteFailure:
    def test_promote_failing_after_its_push_restores_prod_from_previous(self) -> None:
        state = promoted(good_prod(1), 2)  # promote pushed: prod = 2, previous_prod = 1
        assert ds.prod_overwritten_by(state, sha(2), release(2).run_id)
        after = fail_run(state, 2, "promote")
        assert after["prod"]["sha"] == sha(1)
        assert after["prod"]["tag"] == state["previous_prod"]["tag"]
        assert after["previous_prod"] is None
        assert after["staging"]["sha"] == sha(1) and after["staging"]["status"] == "rolled-back"
        assert history_tail(after, 3) == [
            ("fail", "prod", "job promote failed"),
            ("rollback", "prod", "promote"),
            ("rollback", "staging", "promote"),
        ]
        assert ds.validate(after) == []

    def test_a_failed_first_promotion_leaves_no_prod_at_all(self) -> None:
        state = promoted(ds.empty_state(), 1)
        after = fail_run(state, 1, "promote")
        assert after["prod"] is None and after["previous_prod"] is None
        assert after["staging"] is None

    def test_promote_failing_before_its_push_keeps_prod(self) -> None:
        state = staged(good_prod(1), 2)  # promote died before it pushed
        after = fail_run(state, 2, "promote")
        assert after["prod"]["sha"] == sha(1)
        assert [h["env"] for h in after["history"][-2:]] == ["staging", "staging"]

    def test_no_prod_tag_is_ever_recorded_for_the_failed_build(self) -> None:
        state = promoted(good_prod(1), 2)
        failed_tag = state["prod"]["tag"]
        after = fail_run(state, 2, "promote")
        assert failed_tag not in repr((after["prod"], after["previous_prod"], after["staging"]))

    def test_a_rerun_of_an_already_promoted_sha_does_not_roll_prod_back(self) -> None:
        state = promoted(good_prod(1), 2)  # promoted by run 1002
        rerun = ds.stage(state, release(2, run_id=5000), T2)  # same sha, new run
        assert not ds.prod_overwritten_by(rerun, sha(2), 5000)
        after = fail_run(rerun, 2, "smoke", run_id=5000)
        assert after["prod"]["sha"] == sha(2)  # prod untouched: this run never overwrote it
        assert after["staging"]["sha"] == sha(2)


class TestProperties:
    def test_rollback_twice_gives_the_same_prod_and_staging(self) -> None:
        for state, n, reason in [
            (staged(good_prod(1), 2), 2, "smoke"),
            (promoted(good_prod(1), 2), 2, "promote"),
            (staged(ds.empty_state(), 1), 1, "stage"),
        ]:
            once = fail_run(state, n, reason)
            twice = fail_run(once, n, reason)
            for key in ("prod", "previous_prod"):
                assert twice[key] == once[key]
            assert (twice["staging"] or {}).get("sha") == (once["staging"] or {}).get("sha")

    def test_staging_always_matches_prod_after_a_rollback(self) -> None:
        cases = [
            staged(good_prod(1), 2),
            promoted(good_prod(1), 2),
            staged(ds.empty_state(), 1),
            promoted(ds.empty_state(), 1),
        ]
        for state in cases:
            n = int(state["staging"]["sha"][:7], 16)
            after = fail_run(state, n, "soak")
            prod_sha = (after["prod"] or {}).get("sha")
            assert (after["staging"] or {}).get("sha") == prod_sha

    def test_rollback_keeps_the_includes_of_the_build_it_restores(self) -> None:
        state = staged(good_prod(1), 2)
        after = fail_run(state, 2, "smoke")
        assert after["staging"]["includes"] == state["prod"]["includes"]
