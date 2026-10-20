---
name: aistudio
description: Orchestrate video and commercial production in AI Studio. Manage storyboards, character consistency, batch generation, and timeline editing.
---

# AI Studio Skill

This skill allows Antigravity agents and subagents to control and automate video production workflows in **AI Studio**.

## Core Capabilities
- **Projects & Brief:** Inspect project state (`brief.json`, `overview`), create projects, and sync `brief.md`.
- **Storyboard & Shots:** Convert markdown screenplays (`Story.md`) into structured shots and image assets.
- **Budget & Proposals:** Generate budget estimates, inspect rate cards, and draft generation proposals.
- **Verification:** Run multi-angle character checks, audio checks, and consistency linters.
- **Timeline Editor:** Inspect and update timeline clips, text overlays, and audio tracks in `edit.json`.

## Quick CLI Reference
```bash
# List all projects
python3 -m aistudio.cli projects --json

# Overview of a specific project
python3 -m aistudio.cli overview <project_name> --json

# Convert Story.md to shots and images
python3 -m aistudio.cli convert-story <project_name> --json

# Run project verification
python3 -m aistudio.cli verify <project_name> --json

# Check production checklist and pending queue
python3 -m aistudio.cli progress <project_name> --json
```

## Safety & Approval Workflow
- AI agents can perform all operations (story conversion, budget approvals, proposals, shot reviews, project deletion/trash).
- High-impact and spending actions require explicit confirmations (`confirm=true` / confirm with project name), triggering interactive user approval popups in agent environments.
- When running CLI non-interactively, use `-y` and `--json`.
- Run targeted slice tests when modifying code (`python -m unittest tests/test_<domain>.py`).
