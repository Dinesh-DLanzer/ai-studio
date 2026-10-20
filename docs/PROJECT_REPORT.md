# AI Studio: Project Report

Generated 2026-10-16 from the working tree on `main` (99 uncommitted changes).

## 1. What it is

A local-first, single-user app that turns a story idea into a finished AI video. A built-in producer chat ("Tara") interviews the user, writes `Story.md`, and guides them through character sheets, scene frames, video clips, a timeline editor and one ffmpeg-exported MP4. It runs on the user's machine with their own provider keys. It can also be driven by agents (Claude Code, OpenCode) through MCP, a CLI and an HTTP API. MIT licensed, version 0.1.0.

Core promise: **nothing is spent until a human approves that exact price.**

## 2. Architecture

| Layer | Location | Role |
|---|---|---|
| Engine | `aistudio/` | Project files, cost log, discard history, rates, budget, approvals, gates, verification, editor/export, zip import, API keys, secrets |
| Domain layer | `aistudio/domain/` | Newer modular split: projects, storyboard, pipeline, chat, costs, characters, todos, agents, verify |
| Schemas | `aistudio/schemas/` | Typed data models: pipeline, project, storyboard, todos |
| Providers | `aistudio/providers/` | Registry, config, base class and 11 adapters: Anthropic, ChatGPT (OAuth), CLI agent, fake, Google, Kling, OpenAI, OpenCode, OpenRouter, Replicate, Runway |
| Service | `aistudio/service.py` | Single service layer shared by the web API, CLI and MCP |
| Interfaces | `server/app.py`, `aistudio/cli.py`, `aistudio/mcp_server.py` | FastAPI on 127.0.0.1 with token auth; CLI with `--json`; MCP over stdio |
| Frontend | `web/` | React 18, React Router 7, Tailwind 3, Vite 5, TypeScript 5 |
| Tooling | `scripts/`, `start`, `start.bat`, `tools/*.swift` | Cross-platform bootstrap that checks and installs Python, Node, FFmpeg; Swift frame helpers |
| Docs and planning | `README.md`, `GUIDE.md`, `AGENTS.md`, `CLAUDE.md`, `OPENCODE.md`, `plans/`, `SECURITY.md` | |

Python dependencies are only four: fastapi, uvicorn, keyring, Pillow.

## 3. How a video is made

Brief, then storyboard (`Story.md`), then budget approval (a ceiling, with a 130% stop-loss), then characters and places, scene frames, clips (max 3 final attempts per shot), approve or discard, and finally Review & Export.

Safety rules are enforced in the engine, not in prompts:
- Every paid action is a **proposal** with an exact price. Approval is single-use and is invalidated if the prompt, model, price or input image changes.
- Tara, API keys and agents can propose but never approve.
- The server binds to localhost, requires a token and rejects foreign Host/Origin headers.
- Provider keys are write-only and stored in the OS keychain or a private file under `~/.aistudio`.
- Discard never erases anything, and project delete moves the project to `_trash`.
- Each shot is verified by rule checks plus an optional vision review.

## 4. Size and health

| Metric | Value |
|---|---|
| Python | ~13.5k lines (tests included) |
| TypeScript/TSX | ~7.9k lines |
| CSS | ~1k lines |
| Python tests | **428 pass** in ~20s (no network, no money) |
| `tsc --noEmit` | **clean** |
| E2E | 12 Playwright-style scripts in `web/e2e/` (not run for this report) |
| Commits | 5 |

Largest files: `aistudio/editor.py` (1017 lines), `server/app.py` (730), `settings_api.py` (480), `service.py` (467), `chat.py` (403). On the frontend: `StoryDocumentView.tsx` (1006), `editor/Inspector.tsx` (681), `Story.tsx` (554), `ReviewExport.tsx` (500).

## 5. Current state of the working tree

There is a large refactor in flight, uncommitted:
- ~99 changed or untracked paths: modified engine, server, web and tests, plus new files such as `domain/`, `schemas/`, the ChatGPT, CLI-agent and OpenCode adapters, `activity.py`, `character_check.py`, `Costs.tsx` and `web/src/hooks/`.
- `web/src/types.ts` was replaced by `web/src/types/index.ts`.
- `plans/` shows seven completed plans (service modularization, schemas, frontend hooks, terminal agent integration, ChatGPT OAuth, editor transitions and NLE export) and none in progress.
- Agent tooling files (`AGENTS.md`, `CLAUDE.md`, `OPENCODE.md`, `.mcp.json`, `opencode.json`, `.agents/`) are untracked.

## 6. Observations and risks

1. **Uncommitted refactor.** Nearly all recent work exists only in the working tree, and the git history has 5 commits. A single bad checkout could lose it. Commit in logical chunks soon.
2. **Duplicated modules.** `aistudio/chat.py` and `domain/chat.py`, and `aistudio/verify.py` and `domain/verify.py`, coexist. This looks like a mid-migration state. Finish moving the logic and remove the shims, or document which is canonical.
3. **Oversized files.** `editor.py` (1k lines), `app.py` (730) and `StoryDocumentView.tsx` (1k) are the main maintainability hotspots.
4. **Local data size.** `projects/` (454 MB), `_trash/` (183 MB), `projects-backup/` (145 MB) and `graphify-out/` (12 MB) are all gitignored, which is correct. They are large for a laptop, so prune `_trash` and `projects-backup` when you can.
5. **Newly added skills.** `.claude/skills/` now has the taste-skill set and the REA skill. It is untracked, so decide whether to commit or ignore it. These are third-party skills, so review them before committing.
6. **Provider surface.** Eleven adapters plus ChatGPT OAuth and CLI-agent runners widen the auth and subprocess attack surface. `chatgpt_auth.py` and `cli_agent.py` deserve a security review pass, since they handle tokens and spawn processes.
7. **Pricing accuracy.** Prices come from `rates.json` and `settings/models.json`, which the README itself says to verify. A wrong price undermines the approve-exact-price promise, so keep them current.
8. **Language support.** Verified for English and Tamil only (Veo 3.1 Lite).
9. **Scope limits.** Single-user, local only. The editor lacks stickers, filters, effects and auto captions, though plan 07 suggests some of that is now done.

## 7. Suggested next steps

1. Commit the refactor in chunks, then run the 12 E2E scripts against the committed state.
2. Resolve the duplicate `chat` and `verify` modules.
3. Split `editor.py`, `server/app.py` and `StoryDocumentView.tsx`.
4. Run `/code-review` or `/security-review` on the new auth and subprocess adapters.
5. Refresh `rates.json`, and add a test that fails when the rates file is stale.
6. Decide the fate of the untracked agent config and skills.
