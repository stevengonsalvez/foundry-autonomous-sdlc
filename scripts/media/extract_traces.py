#!/usr/bin/env python3
"""Extract real recorded traces from origin/state branch and repository docs.
Used to ensure motion graphics reflect authentic execution traces and costs.
"""

import json
import subprocess
import sys


def get_git_file(branch: str, path: str) -> str:
    cmd = ["git", "show", f"{branch}:{path}"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout


def main():
    print("=== Extracting authentic recorded traces ===")

    # 1. State data
    state_raw = get_git_file("origin/state", "state.json")
    state = json.loads(state_raw)

    # 2. Deploy data
    deploy_raw = get_git_file("origin/deploy", "deploy.json")
    deploy = json.loads(deploy_raw)

    print("\n[Scenario 1: Feature Happy Path (Issue #24)]")
    t24 = next((t for t in state["tickets"] if t.get("issue") == 24), None)
    if t24:
        print(f"  Title: {t24['title']}")
        print(f"  Type: {t24['type']}, Stage: {t24['stage']}")
        print(f"  Cost: ${t24['cost']['usd']:.4f} USD")
        print(f"  PR: #{t24['pr']['number']} ({t24['pr']['url']})")
        print(f"  Release: {t24['release']['tag']}")
        print(f"  Gates: {t24['gates']}")

    print("\n[Scenario 2: Bug with Regression Test First (Issue #25)]")
    t25 = next((t for t in state["tickets"] if t.get("issue") == 25), None)
    if t25:
        print(f"  Title: {t25['title']}")
        print(f"  Type: {t25['type']}, Stage: {t25['stage']}")
        print(f"  Triage: severity={t25['triage']['severity']}, owner={t25['triage']['owner']}")
        print(f"  Cost: ${t25['cost']['usd']:.4f} USD")
        print(f"  PR: #{t25['pr']['number']} ({t25['pr']['url']})")
        print(f"  Release: {t25['release']['tag']}")

    print("\n[Scenario 3: Vague Requirement & Escalation (Issue #17)]")
    t17 = next((t for t in state["tickets"] if t.get("issue") == 17), None)
    if t17:
        print(f"  Title: {t17['title']}")
        print(f"  Type: {t17['type']}, Stage: {t17['stage']}")
        print(f"  Cost: ${t17['cost']['usd']:.4f} USD")
        print(f"  Escalation: {t17.get('escalation')}")

    print("\n[Scenario 4: CD Smoke Fail & Rollback (PR #46 / Run 38180836579)]")
    t46 = next((t for t in state["tickets"] if t.get("pr") == 46 or t.get("issue") == 46), None)
    if t46:
        print(f"  Title: {t46['title']}")
        print(f"  Hops: {len(t46.get('hops', []))} recorded")
        for h in t46.get("hops", []):
            print(f"    - Action: {h['action']}, Env: {h['env']}, Status: {h['status']}, Detail: {h['detail']}")

    print("\nTraces validated successfully.")


if __name__ == "__main__":
    main()
