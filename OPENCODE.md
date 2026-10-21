# OpenCode & Codex Operational Guidelines (`OPENCODE.md`)

## Environment
- AI Studio Python backend runs in `./.venv/bin/python`.
- React frontend runs in `web/` with Vite.
- Non-interactive scriptable CLI is available at `python3 -m aistudio.cli`.
- Default Model configured: `opencode/mimo-v2.6-flash-free`.
- MCP Server: Native tools registered in `ai-studio` namespace.

## Agent Capabilities (Approval by Design)
Terminal agents (OpenCode, Codex, Claude Code, Antigravity CLI) can inspect projects, edit documents, estimate, create proposals, and execute proposals that a human has already approved. They cannot approve budgets, proposals or clips.

### Free read tools
- `get_project`, `read_doc`, `get_brief`, `get_model_setup`, `get_todos`, `get_verification`, `get_proposal`, `get_spec`, `get_costs`, `list_providers`, `production_progress`, `get_batch`, `get_edit`, `unregistered_stills`, `list_recipes`

### Free write tools
- `write_doc`, `update_brief`, `rename_asset`, `rename_shot`, `convert_story`, `update_shots`, `update_images`, `update_edit`, `import_stills`, `add_todo`, `toggle_todo`, `remove_todo`, `export_edit`, `export_project`

### Paid tools (create proposals for human approval)
- `propose`, `analyze_character`, `edit_still`, `extend_clip`, `clip_tool`, `generate_all_plan`, `build_identity_sheet`

### Approval tools (human-only via MCP elicitation or one-time fallback code; agents NEVER call these)
- `estimate`, `approve_budget`, `approve_proposal`, `approve_batch`, `approve_shot`, `run_proposal`, `run_batch`, `reject_proposal`, `set_max_attempts`, `discard`, `restore`

### Human-only tools (never available to crew agents; MCP/HTTP only for humans)
- `list_projects`, `create_project`, `delete_project`, `list_trash`, `restore_trash`, `upload_image`, `list_jobs`, `get_job`, `list_crew_runs`, `get_crew_run`, `search_library`, `plan_recipe`

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
- `aistudio/domain/batches.py`: Batch creation, approval, and execution.
- `aistudio/domain/agents.py`: Crew agent definitions and execution.
- `aistudio/domain/spec.py`: Generation spec resolution (model, price, capabilities).
- `aistudio/domain/verify.py`: Rule and AI verification.
- `aistudio/domain/todos.py`: TODO list management.
- `aistudio/domain/common.py`: Shared utilities and errors.
- `aistudio/schemas/`: Typed Pydantic models for all project JSON files.
- `aistudio/recipes.py`: Recipe validation, planning, and execution.
- `aistudio/crew/`: Studio crew agents, stages, and runtime.
- `aistudio/providers/config.py`: Provider types, role chains, and adapter loading.