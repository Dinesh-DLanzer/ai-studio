---
name: ai-studio
description: Turn a story idea into a finished AI video in AI Studio - interview the user, write the storyboard (Story.md with shared style, characters, backgrounds and shots), fill the brief, estimate the budget, and propose images and clips one at a time for the user to approve (through the MCP tools or the HTTP API; the command-line tool is the fallback). Use when the user gives a story or video idea and wants a storyboard, project files, images or AI video clips in the AI Studio repo.
---

# ai-studio

Works with the AI Studio app in the AI Studio repo folder. **Preferred: the MCP tools (or an API key) against the running app** (see "Working through the app" below). Fallback: the `vidad.py` command-line tool (run commands from the repo folder). Everything is plain files the user can edit. Read `reference.md` (same folder) once before writing prompts: it holds the lessons that cost real money to learn.

## Hard rules (the user set these; never break them)
1. **Never spend without a go-ahead.** Image generation, video runs, re-generation, a model switch and approving a budget each need the user's explicit "go" *for that thing*. "Suggest a model" or "proceed" about something else is not permission. Free actions (dry-run, estimate, status, costs, check, reading) are always fine.
2. **Show the cost first.** Before any paid call, tell the user the exact price: a `propose` result carries it (CLI: `--dry-run`).
3. **One shot at a time.** After each clip: check it, report, and ask "approve, retry, or move on?" before the next. If the user says stop, stop.
4. **Budget gates.** No run without an approved budget. Stop-loss 130% is enforced by the tool. Never re-approve a budget above the figure the user accepted; ask.
5. **Never delete.** Replaced or bad files go to a `_discarded` folder with `discard -m "why"`. Discarded spend is reported separately by `costs`.
6. **Report honestly**, including your own mistakes and what was wasted.

## Flow

### 1. Get the brief (ask, don't assume)
Ask for what is missing: client/brand, goal, audience, platform (default 9:16), length (default ~45s), language of the voice, characters, budget cap, brand colours/logo/CTA, claims to avoid. Offer defaults. Create the project: `python3 vidad.py new <name>`.

### 2. Write `projects/<name>/Story.md`
Copy the structure of `templates/Story.md` (see `projects/godpromo/Story.md` for a finished example): concept, character direction, then **shot by shot**: purpose, visual, camera, action, voice, English, on-screen text, image id, AI prompt. Then the full voice-over script and production notes.
- For EVERY shot decide: **on-camera dialogue** (character speaks, lip-synced) or **off-camera voice-over** or **silent**. Read the storyboard for voice lines before choosing audio on/off.
- Voice lines go in the language's own script (Tamil: Tamil script) plus the English meaning. One short sentence per clip (speech should end inside ~2-3 s of a 4 s clip).
- Keep the on-screen text, logos and end-card graphics for the editor. Do not ask Veo for text or logos.
- Get the user's approval of the storyboard. Edit it with them freely.

### 3. Fill the project files from the storyboard
- `brief.md` (client, goal, platform, length, hook, CTA, budget cap, brand kit, decisions).
- `shots.json`: one entry per shot: `id, model "google/veo-3.1-lite", seconds 4 (6/8 only if needed), resolution "720p", audio true/false, first_frame "stills/<id>.png", prompt, note`. Top level: `aspect_ratio "9:16"`, `audio false`. Follow the prompt recipe in `reference.md`.
- `images.json`: the image list (next step).
- `TODO.md`: fill in the checklists (images to make, language check, brand assets, per-shot run list, edit tasks, file table).
Run `python3 vidad.py estimate <name> --failure 0.2 --draft-rounds 0`, show the total and stop-loss, and ask the user to approve (`approve <name> budget`). Their accepted figure is a ceiling.

### 4. The assets (`images.json`, built from Story.md) - in this order
In the app you do not write `images.json` by hand: `convert_story` builds it from Story.md. Put a `## Shared style` section (added to every image prompt; include the brand hex colours if the user wants them), a `## Characters` section with one `### Name` per character, a `## Backgrounds` section with one `### Place` per place, and in every shot a `**Uses**: name, name` line (its characters, places and uploaded files) plus `**Image**: s01`. Leave a section out when there is none. Uploads the user adds (a logo) are kept when the story is re-applied. What follows is the order and what each entry needs:
1. **Character master sheets**, one per character: full-body views plus a grid of expressions (NEUTRAL, HAPPY, ANGRY, SAD, SURPRISED, THINKING, LAUGHING, CONCERNED), close-ups, clothing detail. Landscape 3:2.
2. **Background sets**, one per place (empty, no people), 3:2. Also a "busy" and an "empty" variant when the story contrasts them.
3. **Scene frames** (`kind: frame`, 9:16, `out: stills/<shot>.png`): each uses `refs` = the character sheet(s) + the background (max 4). These are the Veo first frames.
Every entry: `id, kind, out, aspect_ratio, refs, prompt`. `style` at the top is added to every prompt.
Ask the user how images are made: (a) they supply them, or (b) generate with Qwen Image 3 (about $0.04 each): `python3 vidad.py image <name> <id> --dry-run`, then run it, **look at the image**, and only keep it if the face matches the sheet and the place matches the background. A bad still wastes a $0.20 clip, so get the user's OK on each image. `discard` rejected images (the tool will not overwrite).
Generate in order: sheets, backgrounds, then frames.

### 5. Generate the video, one shot at a time
For shot `sNN`:
```
python3 vidad.py run <name> sNN --stage final --dry-run     # show cost, ask
python3 vidad.py run <name> sNN --stage final               # only after the user says go
python3 vidad.py check <name> sNN                           # frames across the WHOLE clip
```
Then **view every frame** (the Read tool). Report: who appears (only the intended characters?), stray or garbled text, logos, the last second (endings break), speech timing (from the audio level), file/cost. Ask the user to listen (you cannot judge the language by ear). Then:
- Approve: `approve <name> sNN final`.
- Retry: fix the prompt, `discard` the bad clip (`-m reason`), ask before re-running (max 3 attempts per shot).
Never chain clips through last frames (it broke the voice). Generate scene by scene; fix continuity in the edit.

**"Generate all"** mode: only if the user asks. Do the loop above in story order; after EVERY clip stop and ask "proceed to the next scene?". If no, stop and leave everything as is. If yes, continue. The budget gates still apply.

### 6. Change anything, any time
Everything is editable: Story.md, shots.json, images.json, brief.md. After a change that affects cost, re-run `estimate` (it resets approval) and ask the user to re-approve. To replace a file: `discard` it first. To change a shot's model/length/audio: edit its entry and dry-run.

### 7. Hand-off
Fill the clip table in `TODO.md` (shot -> file -> voice -> approved). Run `python3 vidad.py costs <name>` and show USED vs DISCARDED. Editing tasks: trim to the end of speech, on-screen text, logo/end card, music, the platform's AI label, no guaranteed-result claims.

## Working through the app (MCP tools or an API key)
Tools: `list_projects`, `create_project`, `get_project`, `read_doc`, `write_doc`, `get_brief`, `update_brief`, `convert_story`, `update_shots`, `update_images`, `estimate`, `propose`, `get_proposal`, `run_proposal`, `get_costs`, `get_todos`, `get_verification`, `rename_asset`, `rename_shot`, `discard`, `restore`, `get_model_setup`, `list_providers`. The same abilities exist as HTTP routes for an API key (Help > API & Integrations lists them).
The order, which the server enforces: brief, `write_doc` Story.md, `convert_story`, `estimate`, **the user approves the budget in the page**, then for each item in this order `propose` (kind image, target = character, then background, then scene frame ids) -> **the user approves that price in the page ("Waiting for your decision")** -> `run_proposal`; then the same for `kind clip` per shot; the user approves or discards clips. A scene frame is refused before the characters and places it uses exist, and a clip before its scene frame.
You cannot approve budgets, proposals or clips, change providers, keys or limits, or delete projects: those stay with the user. A proposal made with an API key has no approval code.
There is no app-wide mode. A project is a **test project** (simulated and free: placeholders, no key needed) or a **real project** (spends money after approvals). Use a test project to rehearse; never suggest turning a project "real" without explaining the cost. The chat AI in the app is called **Tara**; you do not replace her, you work alongside her through the same files.

## Commands (fallback: the original command-line tool)
`new, estimate, approve, image, run, check, discard, costs, status, report, sync (resolve timed-out jobs), lastframe`. Run `python3 vidad.py -h`.
Models are in `rates.json`; image model is Qwen Image 3 (`qwen/qwen-image-3`), video model is Veo 3.1 Lite.
