---
name: run-plan
description: Execute one AI Studio roadmap plan (plans/not-started/NN-*.md) end to end - branch, lifecycle moves, test-first checklist, the plan's own verification commands, and a completion record.
disable-model-invocation: true
argument-hint: <plan number, e.g. 09>
---

# Run plan $ARGUMENTS

Execute `plans/not-started/$ARGUMENTS-*.md` following `plans/readme.md` and `plans/product-roadmap.md`.

## Before starting
1. Read the plan file completely, plus the roadmap §2 (verified findings) and §7 (owner decisions). Check every plan listed under "Depends on" is in `plans/completed/`. If one is not, stop and say which.
2. Working tree must be clean (`git status`). Branch from the current dev branch: `git switch -c dev/plan-$ARGUMENTS-<slug>`.
3. Move the plan: `git mv` is not possible (plans/ is gitignored), so `mv plans/not-started/$ARGUMENTS-*.md plans/on-processing/` and update its row in `plans/readme.md` to "In progress".

## While working
- Work the **Implementation Checklist** top to bottom, one item at a time, test first (write the failing test, make it pass). Tick each box in the plan file as it lands.
- Anything marked "verify at implementation": check current official docs (context7 MCP) before coding it; write what you found under a `## Verification notes` heading in the plan.
- Never add a paid provider call outside `pipeline.execute` with a `Grant` (plan 09 rule). Never reveal approval codes to chat or agents.
- Run only the plan's own **Verification & Testing** commands while iterating; the Stop hook runs the full Python suite.
- Commit per checklist group with a clear message; do not push unless the user asks.

## Finishing
1. Run every command in the plan's Verification section and paste the results into the plan under `## Verification results` (date, command, pass/fail).
2. Run the `spend-safety-reviewer` subagent if the diff touches pipeline, approvals, gates, roles, pricing, mcp_server, chat, or any adapter.
3. Move the plan to `plans/completed/`, mark its `plans/readme.md` row "Completed (Verified)", and tell the user: what shipped, test results, anything skipped, and the next plan in the roadmap order.
