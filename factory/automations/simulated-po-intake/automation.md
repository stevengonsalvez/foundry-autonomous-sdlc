---
description: Every four hours the simulated product owner files a new issue from ROADMAP.md.
trigger:
  type: schedule
  every: 4h
runner: foreman
agent: sdlc-product-owner
action:
  workflow: SimulatedPoIntakeWorkflow
---

Reads the next unfiled item from `ROADMAP.md` and opens a GitHub issue labelled as a simulated
product owner request. The normal poll then picks it up like any other owner-opened issue.
