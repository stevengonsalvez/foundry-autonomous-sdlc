---
description: Poll GitHub every minute and start or signal one WorkItemWorkflow per owner-opened issue or pull request.
trigger:
  type: schedule
  every: 1m
ownerOnly: true
runner: foreman
action:
  workflow: PollWorkflow
---

Lists open issues and pull requests in each repository named in factory.yaml. Items not opened by
the repository owner are ignored and cost nothing. For each remaining item the poll starts
`WorkItemWorkflow` with the fixed id `issue-N` or `pr-N`, so a duplicate event is a no-op, and
signals `checks_changed` or `pr_changed` when the item has moved since the last poll.
