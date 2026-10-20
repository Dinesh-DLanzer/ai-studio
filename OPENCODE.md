# OpenCode & Codex Operational Guidelines (`OPENCODE.md`)

## Environment
- AI Studio Python backend runs in `./.venv/bin/python`.
- React frontend runs in `web/` with Vite.
- Non-interactive scriptable CLI is available at `python3 -m aistudio.cli`.
- Default Model configured: `opencode/mimo-v2.6-flash-free`.
- MCP Server: Native tools registered in `ai-studio` namespace.

## Agent Capabilities (Approval by Design)
Terminal agents (OpenCode, Codex, Claude Code, Antigravity CLI) can inspect projects, edit documents, estimate, create proposals, and execute proposals that a human has already approved. They cannot approve budgets, proposals or clips.
- **Story & Assets**: `convert_story`, `update_shots`, `update_images`, `import_stills`, `upload_image`
- **Budget & Proposals**: `estimate`, human approval requests via `approve_budget`/`approve_proposal`, `propose`, `reject_proposal`, `run_proposal`
- **Shot Approvals**: `approve_shot`, `discard`, `restore`
- **Project Management**: `create_project`, `delete_project` (moves to `_trash`), `list_trash`, `restore_trash`, `export_project`
- **Timeline Editing**: `get_edit`, `update_edit`, `export_edit`

### Human approval and MCP elicitation
For high-impact or spending operations:
1. `estimate` and `propose` are free and only create the exact request for review.
2. With an MCP client that advertises form elicitation, `approve_budget`, `approve_proposal`, and a pending `run_proposal` send `elicitation/create`. Continue only after the client returns `accept` with the required approval checkbox set to true.
3. `confirm=true` is rejected; an agent-supplied boolean is not human approval.
4. Without elicitation, the server returns a one-time challenge. The HMAC-derived code is shown only in the local web notification and `aistudio serve` stderr, never in an MCP response or project folder. Pass that code and its id back only after the human has read it.
5. `delete_project` keeps `confirm=<project name>` because it is a restorable, non-spending trash move.
6. **Never** approve a real proposal in automated work; use fake/test projects for tests.
7. **In CLI subcommands**:
   - `approve-budget`, `approve`, and `approve-shot` are human-facing commands. Agents must not use `-y` as a substitute for human approval.
   - After a human has approved the exact proposal, an agent may run it with `run <project> <proposal_id> -y`; free/status operations may also use `-y` in automated scripts.
   - For human supervision, omit `-y` to prompt interactively. Always append `--json` when parsing programmatically.

## Domain Structure
- `aistudio/domain/projects.py`: Filesystem, project creation, trash, asset renaming.
- `aistudio/domain/storyboard.py`: Story conversion, shots, timeline editing.
- `aistudio/domain/pipeline.py`: Proposal queue, batch generation plans.
- `aistudio/domain/characters.py`: Character multi-angle vision checks.
- `aistudio/domain/costs.py`: Pricing, budget estimation, cost log.
- `aistudio/schemas/`: Typed Pydantic models for all project JSON files.
