# Claude Code Guidelines for AI Studio (`CLAUDE.md`)

This repository is **AI Studio**, a local-first video and commercial production pipeline.

---

## 1. Approval by Design
* **Agents propose; humans approve:**
  - Story conversion, document edits, estimates, proposal creation, and already-approved execution are available to Claude Code via MCP and the HTTP API.
  - Budget and paid proposal approval are human-only. `confirm=true` is not an approval signal and is rejected by MCP.
  - MCP clients advertising form elicitation receive an `elicitation/create` dialog showing the exact request and price. Clients without elicitation receive a one-time code challenge; the code appears only in the local AI Studio notification and `aistudio serve` stderr, never in the MCP response or project files.
  - **CLI-first human approval:** The terminal remains a supported human-facing approval channel. Agents must ask the human and pass the elicitation response or one-time fallback code; never claim that an agent approved anything.
* **Non-Interactive Execution:**
  - Use `--json` for machine-readable CLI output. `-y` / `--yes` is only for free operations or executing an exact proposal after a human has already approved it; never use it for budget, proposal, or clip approval.

---

## 2. MCP Tools Available (`ai-studio`)
When running in Claude Code, the following tools are available via MCP (`.mcp.json`):
* `list_projects`: List all video projects with spend and budget status.
* `get_project`: Get project overview (shots, images, budget, files, proposals).
* `create_project`: Create a new project folder from templates.
* `delete_project`: Move project to `_trash` (restorable) with `confirm="yes"`.
* `list_trash` / `restore_trash`: Manage and restore trashed projects.
* `convert_story`: Parse `Story.md` and generate `shots.json` and `images.json`.
* `estimate` / `approve_budget`: Estimate and request human approval of the project budget ceiling through elicitation or the one-time fallback code.
* `propose` / `approve_proposal` / `run_proposal`: Propose, request human approval through elicitation or the fallback code, and execute only an approved proposal.
* `approve_shot` / `discard` / `restore`: Inspect clip decisions and discard/restore files; clip approval is human-only and the MCP approve_shot tool refuses agent calls.
* `get_verification`: Check rule violations and model reviews.
* `production_progress`: Get production checklist groups and queue items.
* `generate_all_plan`: Compute exact prices and generate batch proposals for pending assets.
* `get_edit` / `update_edit` / `export_edit`: Inspect, update, and render timeline video editor.
* `add_todo` / `toggle_todo` / `remove_todo`: Manage tasks on the project TODO checklist.
* `export_project`: Downloadable zip backup of the project.

---

## 3. Useful Bash Commands
```bash
# List projects as JSON
python3 -m aistudio.cli projects --json

# Inspect project details
python3 -m aistudio.cli overview <project> --json

# Convert Story.md to storyboard shots
python3 -m aistudio.cli convert-story <project> --json

# Run targeted unit tests (never run full suite unnecessarily)
./.venv/bin/python -m unittest tests/test_service.py tests/test_mcp.py

# Verify frontend TypeScript types
cd web && npx tsc --noEmit
```
