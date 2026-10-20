# Claude Code Guidelines for AI Studio (`CLAUDE.md`)

This repository is **AI Studio**, a local-first video and commercial production pipeline.

---

## 1. Approval by Design
* **All production actions are supported:**
  - Story conversion, asset generation, proposal approval, budget approval, shot review, and project trashing/deletion are all available to Claude Code via MCP and CLI.
  - High-impact and spending actions (`delete_project`, `approve_budget`, `approve_proposal`, `run_proposal`) require confirmation arguments (`confirm=true` or matching project name), which trigger Claude Code's interactive permission popup before execution.
  - **CLI-First Approvals (Never Redirect to Web UI):** Terminal agents have full capability to request user confirmation and approve budget and proposals directly in the CLI. Never instruct the user to open the web UI for approvals.
* **Non-Interactive Execution:**
  - When running `aistudio` CLI subcommands in bash, append `--json` and `-y` / `--yes` for automated script pipelines, or omit `-y` for interactive human prompts.

---

## 2. MCP Tools Available (`ai-studio`)
When running in Claude Code, the following tools are available via MCP (`.mcp.json`):
* `list_projects`: List all video projects with spend and budget status.
* `get_project`: Get project overview (shots, images, budget, files, proposals).
* `create_project`: Create a new project folder from templates.
* `delete_project`: Move project to `_trash` (restorable) with `confirm="yes"`.
* `list_trash` / `restore_trash`: Manage and restore trashed projects.
* `convert_story`: Parse `Story.md` and generate `shots.json` and `images.json`.
* `estimate` / `approve_budget`: Estimate and approve project budget ceiling (`confirm=true`).
* `propose` / `approve_proposal` / `run_proposal`: Propose, approve (`confirm=true`), and execute generation.
* `approve_shot` / `discard` / `restore`: Review, approve clips, or discard with reasons.
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
