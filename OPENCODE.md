# OpenCode & Codex Operational Guidelines (`OPENCODE.md`)

## Environment
- AI Studio Python backend runs in `./.venv/bin/python`.
- React frontend runs in `web/` with Vite.
- Non-interactive scriptable CLI is available at `python3 -m aistudio.cli`.
- Default Model configured: `opencode/mimo-v2.6-flash-free`.
- MCP Server: Native tools registered in `ai-studio` namespace.

## Full Agent Capabilities (Approval by Design)
Terminal agents (OpenCode, Codex, Claude Code, Antigravity CLI) can perform **ALL** production actions end-to-end:
- **Story & Assets**: `convert_story`, `update_shots`, `update_images`, `import_stills`, `upload_image`
- **Budget & Proposals**: `estimate`, `approve_budget`, `propose`, `approve_proposal`, `reject_proposal`, `run_proposal`
- **Shot Approvals**: `approve_shot`, `discard`, `restore`
- **Project Management**: `create_project`, `delete_project` (moves to `_trash`), `list_trash`, `restore_trash`, `export_project`
- **Timeline Editing**: `get_edit`, `update_edit`, `export_edit`

### Interactive Approval Popups & Confirmations (CLI-First)
For high-impact, spend, or destructive operations:
1. **Budget Approvals**:
   - When the project budget needs approval (or after calling `estimate`), prompt the user in terminal:
     `"Approve estimated project budget of $<amount> (stop-loss: $<stop_loss>)?"`
   - When confirmed, call `approve_budget(name="<project>", confirm=true)`.
2. **Paid Generation Proposals**:
   - When an image or clip proposal is generated via `propose`, prompt the user in terminal:
     `"Approve <kind> '<target>' with <model> for $<price>?"`
   - When confirmed, call `run_proposal(name="<project>", id="<proposal_id>", confirm=true)` to approve and execute in one step.
   - Or call `approve_proposal(name="<project>", id="<proposal_id>", confirm=true)` followed by `run_proposal(name="<project>", id="<proposal_id>")`.
3. **CRITICAL: NEVER Redirect the User to the Web UI**:
   - Terminal agents have **full authority and capability** to request approval and execute actions directly in the CLI.
   - **NEVER** instruct the user to "open the AI Studio web UI to approve". Always ask the user right here in the CLI!
4. **In CLI Subcommands**:
   - For automated scripts, pass `-y` to skip terminal prompts:
     ```bash
     python3 -m aistudio.cli delete-project <project> -y
     python3 -m aistudio.cli approve-budget <project> -y
     python3 -m aistudio.cli approve <project> <proposal_id> -y
     python3 -m aistudio.cli run <project> <proposal_id> -y
     ```
   - For human supervision, omit `-y` to prompt interactively.
   - Always append `--json` when parsing programmatically.

## Domain Structure
- `aistudio/domain/projects.py`: Filesystem, project creation, trash, asset renaming.
- `aistudio/domain/storyboard.py`: Story conversion, shots, timeline editing.
- `aistudio/domain/pipeline.py`: Proposal queue, batch generation plans.
- `aistudio/domain/characters.py`: Character multi-angle vision checks.
- `aistudio/domain/costs.py`: Pricing, budget estimation, cost log.
- `aistudio/schemas/`: Typed Pydantic models for all project JSON files.
