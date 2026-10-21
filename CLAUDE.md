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
When running in Claude Code, the following tools are available via MCP (`.mcp.json`), derived from `aistudio/tool_registry.py`:

**cost_class = free | paid | approval | human_only** (approval/human_only tools are NEVER available to crew agents)

### Free read tools
| Tool | Purpose | Cost Class |
|------|---------|------------|
| `get_project` | Overview: shots, images, budget, costs (used vs discarded), proposals, files, reviews | free |
| `read_doc` | Read Story.md, brief.md or TODO.md | free |
| `get_brief` | The brief: every field, its value, and which required fields are still missing | free |
| `get_model_setup` | Read-only: connected AI providers (state only, never keys) and model chains per role | free |
| `get_todos` | Automatic progress steps plus the manual TODO list | free |
| `get_verification` | Verification of brief, story, assets, shots and todos: rule findings plus AI review | free |
| `get_proposal` | Status of a proposal: pending \| approved \| used \| rejected \| expired \| void | free |
| `get_spec` | Read-only preview of one generation: model, seconds, frames, references, capability profile, price, warnings | free |
| `get_costs` | Cost log, used vs discarded split, budget | free |
| `list_providers` | Connected AI providers (id, label, type, status) | free |
| `production_progress` | Get production checklist groups, queue items, and next action | free |
| `get_batch` | Status of a batch and each of its items | free |
| `get_edit` | Get timeline video edit structure (edit.json) and tool status | free |
| `unregistered_stills` | Find unregistered images in the stills folder that can be added to project assets | free |
| `list_recipes` | Read-only: one-click recipes with their inputs, and whether every step can run with configured models | free |

### Free write tools
| Tool | Purpose | Cost Class |
|------|---------|------------|
| `write_doc` | Write Story.md, brief.md or TODO.md (plain text) | free |
| `update_brief` | Fill brief fields (brand, goal, story, audience, platform, length_seconds, language, characters, setting, cta, brand_assets, claims_to_avoid, budget_cap) | free |
| `rename_asset` | Rename an image asset id everywhere (files, references, cost log) | free |
| `rename_shot` | Rename a shot id everywhere (clips, cost log, discarded history) | free |
| `convert_story` | Parse Story.md and write shots.json + images.json. Overwrites both | free |
| `update_shots` | Replace shots.json (validated). Changing shots needs a new estimate and human re-approval | free |
| `update_images` | Replace images.json (validated) | free |
| `update_edit` | Update timeline video edit structure (edit.json) | free |
| `import_stills` | Import unregistered stills into project assets (images.json) | free |
| `add_todo` | Add a task to the project TODO list | free |
| `toggle_todo` | Toggle task completion status on the project TODO list | free |
| `remove_todo` | Remove a task from the project TODO list | free |
| `export_edit` | Render / export the timeline edited video (edit.json) into a final video file | free |
| `export_project` | Export the project as a downloadable zip archive | free |

### Paid tools (agents may call; create proposals for human approval)
| Tool | Purpose | Cost Class |
|------|---------|------------|
| `propose` | Propose a PAID action (image \| clip \| review); target = image id or shot id | paid |
| `analyze_character` | Propose a paid multi-angle consistency review on a character asset image | paid |
| `edit_still` | Propose an inpaint, outpaint or background-swap edit of an existing still | paid |
| `extend_clip` | Propose extending an existing video clip forward with a continuation prompt | paid |
| `clip_tool` | Propose a PAID AI clip tool (upscale_ai, reframe_ai, restyle, replace, motion_transfer, character_swap) | paid |
| `generate_all_plan` | Freeze the plan for everything left to generate as a batch (exact prices; nothing spent) | paid |
| `build_identity_sheet` | Build a character's identity sheet: batch of image proposals for missing views | paid |

### Approval tools (human-only via MCP elicitation or one-time fallback code; agents NEVER call these)
| Tool | Purpose | Cost Class |
|------|---------|------------|
| `estimate` | Compute budget estimate (free). Human must approve through MCP elicitation or fallback code | approval |
| `approve_budget` | Request human approval for the exact estimated budget. Uses elicitation or fallback code | approval |
| `approve_proposal` | Request human approval for a pending proposal. Uses elicitation or fallback code | approval |
| `approve_batch` | Request human approval for the exact batch total. Uses elicitation or fallback code | approval |
| `approve_shot` | Human-only clip decision. Agents may inspect but cannot approve through MCP | approval |
| `run_proposal` | Execute a proposal only after human approval. Pending proposals use elicitation or fallback code | approval |
| `run_batch` | Run a batch a human already approved, item by item | approval |
| `reject_proposal` | Reject and cancel a pending proposal | approval |
| `set_max_attempts` | Human-only attempt limit setting. Agents cannot change generation attempt limits | approval |
| `discard` | Move a clip/still to _discarded (never deletes) with a reason | approval |
| `restore` | Restore a discarded file | approval |

### Human-only tools (never available to crew agents; MCP/HTTP only for humans)
| Tool | Purpose | Cost Class |
|------|---------|------------|
| `list_projects` | List projects with spend and budget status | human_only |
| `create_project` | Create a project folder from the guided templates | human_only |
| `delete_project` | Move a project to _trash (restorable). Requires human confirmation matching project name | human_only |
| `list_trash` | List deleted projects available in trash for restoration | human_only |
| `restore_trash` | Restore a project from trash | human_only |
| `upload_image` | Upload or import an image file into project assets (stills/ and images.json) | human_only |
| `list_jobs` | Jobs in the durable job ledger with state (read-only) | human_only |
| `get_job` | One job from the ledger by id (read-only) | human_only |
| `list_crew_runs` | Read-only: the studio crew's runs in a project | human_only |
| `get_crew_run` | Read-only: one crew run with step log, diffs, proposals and batch | human_only |
| `search_library` | Search the workspace library of generated media (human-session only) | human_only |
| `plan_recipe` | Plan a recipe in a project: validates inputs, prices steps, creates awaiting-approval batch | human_only |

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