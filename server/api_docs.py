"""The single description of every HTTP route: used by the Help page (API reference), by the key scope check (agent=True means an API key may call it)
and by a test that fails when a route is added without being described here.

Fields: (method, path, agent, group, summary, body, returns).  agent=True: allowed for API keys (same power as the MCP tools).  False: needs the
page's session token (a human): approvals, budget, providers, keys, limits, deleting.
"""
GROUPS = ["Projects", "Story and documents", "Chat (producer)", "Assets and shots", "Budget, proposals and approvals", "Generation jobs", "Review and Export",
          "Costs and verification", "Library", "Providers, models and limits", "Integrations", "Files and utility", "Settings", "ComfyUI workflows"]

R = [
    ("GET", "/api/library", False, "Library", "Search the workspace generation library. Read-only; results can span projects.", "query parameters", '{"items": [...], "total"}'),
    ("GET", "/api/library/{id}", False, "Library", "Read one library item.", "-", "library item"),
    ("GET", "/api/library/{id}/file", False, "Library", "The library item's media file (for thumbnails and previews). Human session only.", "-", "media file"),
    ("POST", "/api/library/{id}/favorite", False, "Library", "Mark or unmark a library item as favorite. Human session only.", '{"on": true}', "library item"),
    ("POST", "/api/library/rebuild", False, "Library", "Rebuild the index from project media and cost logs. Human session only.", "-", '{"count": 0}'),
    ("POST", "/api/library/promote", False, "Library", "Copy a project asset into the workspace library. Human session only.", '{"project": "...", "file": "stills/hero.png"}', "library item"),
    ("POST", "/api/library/use", False, "Library", "Copy a workspace library asset into a project. Human session only.", '{"id": "...", "project": "...", "kind": "image"}', "library item"),
    ("POST", "/api/library/remix", False, "Library", "Return a prefilled proposal request; does not create a proposal or spend money. Human session only.", '{"id": "...", "project": "..."}', "proposal request"),
    ("GET", "/api/recipes", True, "Budget, proposals and approvals", "List recipes (one-click tools) with whether the configured models can run every step, and why not. ?project= checks that project's models; ?available=1 hides the rest. Free.", "query parameters", '{"recipes": [{id, label, category, inputs, available, reasons, skipped}]}'),
    ("POST", "/api/projects/{name}/recipes/{rid}/plan", False, "Budget, proposals and approvals", "Plan a recipe: validate the inputs, price every paid step and freeze ONE awaiting-approval batch whose total is the sum of its items. Nothing is approved, run or spent; a human approves the batch (the batch approve route) and starts it (the batch run route). Human session only. Recipes never target public figures; real-person recipes need a recorded consent.", '{"inputs": {"product": "stills/p.png", "setting": "studio"}}', "batch object (awaiting_approval) with a recipe summary"),
    # ---- projects
    ("GET", "/api/projects", True, "Projects", "List projects.", "-", '{"projects": [{name, shots, assets, spent, estimate, approved, test, favorite}]}'),
    ("POST", "/api/projects", True, "Projects", "Create a project from the guided templates, optionally from a format (see /api/formats) and a workspace brand kit (copied into the project).", '{"name": "my-ad", "test_pipeline": false, "format"?: "instagram-reel", "brand_kit"?: "acme"}', '{"name": "my-ad"}'),
    ("GET", "/api/formats", True, "Projects", "The project formats (aspect ratio, shots, seconds per shot, safe area, caption, suggested models). Static files; nothing is chosen or spent.", "-", '{"formats": [...]}'),
    ("GET", "/api/camera-presets", True, "Assets and shots", "The named camera presets (each maps to a shot direction). Static catalog.", "-", '{"presets": [{id, name, direction, description}]}'),
    ("GET", "/api/brand-kits", False, "Projects", "List the workspace brand kits and the font families available. Human session only.", "-", '{"kits": [...], "fonts": [...]}'),
    ("POST", "/api/brand-kits", False, "Projects", "Create a brand kit; a base64 logo gives the palette from its dominant colours. Human session only.", '{"name": "Acme", "logo_b64"?: "...", "style_words"?: "...", ...}', "kit"),
    ("GET", "/api/brand-kits/{kid}", False, "Projects", "One brand kit. Human session only.", "-", "kit"),
    ("PUT", "/api/brand-kits/{kid}", False, "Projects", "Edit a brand kit's name, palette, fonts, caption, watermark, end card, voice, style words and avoid list. Human session only.", "kit fields", "kit"),
    ("DELETE", "/api/brand-kits/{kid}", False, "Projects", "Move a brand kit to brand_kits/_trash (never erases). Human session only.", "-", '{"ok": true}'),
    ("GET", "/api/brand-kits/{kid}/logo", False, "Projects", "The kit's logo image. Human session only.", "-", "image"),
    ("POST", "/api/projects/import", False, "Projects", "Create a project from a zip made by Export project. The body is the raw zip; ?name= and ?filename= are optional. Every file is checked first; approvals inside the zip are dropped.", "raw .zip bytes (up to 2 GB)", '{"name", "notes": [...], "files"} or 400 {"detail", "problems": [...]}'),
    ("GET", "/api/projects/{name}", True, "Projects", "Everything about one project: shots, images, budget, costs (used and discarded), proposals, files, reviews, and whether it is a test project.", "-", "overview object"),
    ("GET", "/api/projects/{name}/activity", True, "Projects", "What happened in the project recently (generations, approvals, edits).", "-", '{"activity": [...]}'),
    ("GET", "/api/approval-notifications", False, "Budget, proposals and approvals", "Human-only approval code notifications from the local MCP fallback.", "-", '{"notifications": [{"id", "code", "message", "project", "expires"}]}'),
    ("GET", "/api/projects/{name}/events", False, "Projects", "Live stream of project changes (server-sent events) so an open page stays current.", "-", "text/event-stream"),
    ("POST", "/api/projects/{name}/favorite", False, "Projects", "Mark or unmark a favorite.", '{"on": true}', '{"name", "favorite"}'),
    ("POST", "/api/projects/{name}/rename", False, "Projects", "Rename the project folder.", '{"new": "better-name"}', '{"name": "better-name"}'),
    ("DELETE", "/api/projects/{name}", False, "Projects", "Move the project to the trash (never erases). Needs the exact name as confirmation.", '{"confirm": "<name>"}', '{"trash": "<id>"}'),
    ("GET", "/api/projects/{name}/export-project", False, "Projects", "Download the whole project folder as a zip. ?include_discarded=1 adds the discarded files.", "-", "application/zip"),
    ("GET", "/api/trash", False, "Projects", "List deleted (archived) projects.", "-", '{"items": [{id, name, when, files}]}'),
    ("POST", "/api/trash/{tid}/restore", False, "Projects", "Restore a deleted project, optionally under another name.", '{"as_name": "other"} (optional)', '{"name"}'),
    # ---- story and documents
    ("GET", "/api/projects/{name}/docs/{fn}", True, "Story and documents", "Read Story.md, brief.md or TODO.md.", "-", '{"text": "..."}'),
    ("PUT", "/api/projects/{name}/docs/{fn}", True, "Story and documents", "Write Story.md, brief.md or TODO.md. Saving Story.md rebuilds shots and assets from it.", '{"text": "..."}', '{"ok": true, ...}'),
    ("POST", "/api/projects/{name}/story/convert", True, "Story and documents", "Parse Story.md into shots.json and images.json (characters, backgrounds, scene frames, shared style). Uploads are kept.", "-", '{"shots", "images"}'),
    ("GET", "/api/projects/{name}/story/pending", False, "Story and documents", "The storyboard the producer drafted and that waits for a human to apply.", "-", '{"text"}'),
    ("POST", "/api/projects/{name}/story/apply-pending", False, "Story and documents", "Apply the drafted storyboard (refuses if clips are already approved).", "-", '{"shots", "images"}'),
    ("POST", "/api/projects/{name}/story/discard-pending", False, "Story and documents", "Throw the draft away.", "-", '{"ok": true}'),
    ("PUT", "/api/projects/{name}/shots", True, "Story and documents", "Replace shots.json (validated). A change needs a new estimate and a new budget approval.", "shots.json document", '{"ok": true}'),
    ("PUT", "/api/projects/{name}/images", True, "Story and documents", "Replace images.json (validated).", "images.json document", '{"ok": true}'),
    ("GET", "/api/projects/{name}/brief", True, "Story and documents", "The brief: every field, its value and what is still missing.", "-", "brief object"),
    ("PUT", "/api/projects/{name}/brief", True, "Story and documents", "Fill brief fields (brand, goal, story, length_seconds, language, characters, setting, brand_assets, budget_cap, ...).", '{"updates": {"brand": "..."}}', "brief object"),
    ("GET", "/api/projects/{name}/todos", True, "Story and documents", "Automatic progress steps and the manual TODO list.", "-", '{"auto": [...], "manual": [...]}'),
    ("POST", "/api/projects/{name}/todos", False, "Story and documents", "Add a manual TODO.", '{"title": "..."}', "todos object"),
    ("POST", "/api/projects/{name}/todos/{tid}/toggle", False, "Story and documents", "Tick or untick a manual TODO.", "-", "todos object"),
    ("DELETE", "/api/projects/{name}/todos/{tid}", False, "Story and documents", "Remove a manual TODO.", "-", "todos object"),
    ("GET", "/api/languages", True, "Story and documents", "Voice languages with whether they were tested with the video model.", "-", '{"languages": [...]}'),
    # ---- chat
    ("GET", "/api/projects/{name}/chat", True, "Chat (producer)", "Chat history, the brief, and the production checklist (groups with counts, the next step, and the queue of everything left to generate).", "-", '{"messages", "brief", "progress", "mode"}'),
    ("POST", "/api/projects/{name}/chat", False, "Chat (producer)", "Send one message to the producer (uses your chat model; free models unless you allowed paid). Optional attachments are ids of uploaded images.", '{"text": "...", "attachments": ["logo"], "prefs": {}}', "chat state + reply"),
    # ---- assets and shots
    ("POST", "/api/projects/{name}/upload", False, "Assets and shots", "Upload an image to stills/<id>.<ext> (PNG, JPEG, WebP, GIF, BMP, TIFF, HEIC; converted if needed). ?rel=stills/<id>.png&replace=1.", "raw image bytes (up to 25 MB)", '{"ok": true}'),
    ("POST", "/api/projects/{name}/characters/{aid}/identity-sheet", True, "Budget, proposals and approvals", "Freeze a character's missing identity views (front, three-quarter, profile, full-body, expression) as a batch of image proposals conditioned on the master image. Creates files only; a human must approve the batch total before anything is spent.", '{"views"?: ["front", "profile"]}', "batch object (awaiting_approval)"),
    ("POST", "/api/projects/{name}/remix", False, "Budget, proposals and approvals", "Create a PROPOSAL pre-filled from an output's .meta.json (same kind, target and, for edits, source). Nothing is approved or spent; a human approves it like any other proposal. Human session only.", '{"meta": "stills/hero.png.meta.json"}', '{"proposal", "from", "changed", "seed", "note"}'),
    ("POST", "/api/projects/{name}/variants", True, "Budget, proposals and approvals", "Freeze N candidates (2-4) of one still or clip as ONE batch awaiting approval: N separate items, each with its own price, request hash and proposal; the total is N times the unit price. Nothing is approved or spent; a human approves the batch.", '{"kind": "image|clip", "target": "s01", "count": 3}', "batch object (awaiting_approval)"),
    ("POST", "/api/projects/{name}/variants/select", False, "Assets and shots", "Choose version k of a still or clip (a human decision). The other versions are moved to _discarded with their cost (never deleted); the shot or asset records selected_version.", '{"kind": "image|clip", "target": "s01", "version": 2}', "{kind, target, selected_version, file, discarded}"),
    ("POST", "/api/projects/{name}/drift-check", True, "Assets and shots", "Create a proposal for a paid identity-drift check of a shot or still (scores each character against its reference images, stored in checks/<id>.json; verification flags scores below 0.6). Nothing is spent until a human approves the proposal.", '{"target": "s01"}', "proposal object"),
    ("GET", "/api/projects/{name}/consent", True, "Assets and shots", "Read the project's consent records (real people, cloned voices).", "-", '{"consent": [{subject, statement, date, kind}]}'),
    ("POST", "/api/projects/{name}/consent/mark", False, "Assets and shots", "Mark an asset's current file bytes as showing a real person (human session only). Paid tools then need consent bound to those exact bytes, even if an agent later clears the asset's real_person flag.", '{"asset_id": "maya"}', "{asset, sha}"),
    ("POST", "/api/projects/{name}/consent", False, "Assets and shots", "Record consent for a real person or a voice (human session only; API keys, MCP and the crew cannot). Generation with an asset marked real_person is refused without it.", '{"subject": "Asha Rao", "statement": "I agree ...", "kind": "real_person|voice"}', "the consent entry"),
    ("POST", "/api/projects/{name}/character/analyze", True, "Assets and shots", "Create a proposal for paid character-image analysis; nothing is spent until a human approves the proposal.", '{"rel": "stills/gandhi.png"}', 'proposal object'),
    ("GET", "/api/projects/{name}/stills/unregistered", False, "Assets and shots", "Images in stills/ that are not in the asset list yet, with a category guess.", "-", '{"files": [...]}'),
    ("POST", "/api/projects/{name}/stills/import", False, "Assets and shots", "Register existing images as assets (renames files to <id>.<ext>).", '{"items": [{"file", "id", "kind"}]}', "overview object"),
    ("POST", "/api/projects/{name}/assets/{aid}/rename", True, "Assets and shots", "Rename an asset id everywhere (files, references, shots, cost log).", '{"new": "..."}', "overview object"),
    ("POST", "/api/projects/{name}/shots/{sid}/rename", True, "Assets and shots", "Rename a shot id everywhere (clips, cost log, discarded history).", '{"new": "..."}', "overview object"),
    ("POST", "/api/projects/{name}/shots/{shot}/approve", False, "Assets and shots", "Approve the newest completed clip of a shot (a human decision).", "-", "shot"),
    ("POST", "/api/projects/{name}/shots/{shot}/camera-move", False, "Assets and shots", "Classify a camera move from sampled camera world matrices (the Blender add-on sends them) and PROPOSE a direction. Nothing is saved, nothing is spent; the direction route applies it. Human session or paired device token only.", '{"samples": [{"frame": 1, "matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}], "fps": 24.0, "lens_samples"?: [{"focal_length": 50.0}], "target"?: [0, 0, 0]}', '{"shot", "classification": {"movement", "speed", "confidence", "evidence"}, "direction": {...}, "saved": false}'),
    ("POST", "/api/projects/{name}/shots/{shot}/direction", False, "Assets and shots", "Apply a camera direction to a shot. The direction is validated against the direction schema (movement, framing, angle, lens_mm...) and saved with the document history. Human session only.", '{"direction": {"movement": "dolly-in", "speed": "normal"}, "replace"?: false}', '{"shot", "direction"}'),
    ("POST", "/api/projects/{name}/previs/render", False, "Generation jobs", "Render the blocking frames of some shots from a .blend inside the project with headless Blender. A free local ledger job (no provider, no cost); the frames land in the project's previs/ folder and are NOT registered as stills. Human session only.", '{"blend": "scenes/main.blend", "shots": ["s01", "s02"]}', '{"job": "<id>"}'),
    ("GET", "/api/projects/{name}/previs", False, "Generation jobs", "The frames rendered into the project's previs/ folder, with their size and whether an asset already uses them. Human session only.", "-", '{"out_dir": "previs", "outputs": [{"file", "name", "shot", "bytes", "image", "registered"}]}'),
    ("POST", "/api/projects/{name}/discard", True, "Assets and shots", "Move a clip or still to _discarded with a reason (never deletes).", '{"rel": "clips/s01_final_a1.mp4", "reason": "..."}', "discard record"),
    ("POST", "/api/projects/{name}/restore", True, "Assets and shots", "Restore a discarded file.", '{"rel": "clips/_discarded/..."}', '{"file"}'),
    ("POST", "/api/projects/{name}/stills/{shot_id}/edit", True, "Assets and shots", "Create a proposal for an inpaint, outpaint or background-swap edit; nothing is spent until a human approves it.", '{"prompt": "...", "edit_mode": "inpaint_insertion", "mask_mode": "MASK_MODE_BACKGROUND"}', 'proposal object'),
    ("POST", "/api/projects/{name}/clips/{shot_id}/tool", True, "Assets and shots", "Create a proposal for a paid AI clip tool on an existing clip (upscale_ai, reframe_ai, restyle, replace, motion_transfer, character_swap). Nothing is spent until a human approves the exact price; the result is a new version beside the clip. Refused when no enabled model lists the task and implements it, or when a real person's consent is missing.", '{"tool": "upscale_ai", "prompt": "...", "scale": 2, "aspect_ratio": "9:16", "target": "object|background", "reference": "clips/driver.mp4", "subject": "Asha Rao", "seconds": 5}', 'proposal object'),
    ("POST", "/api/projects/{name}/audio/tool", True, "Assets and shots", "Create a proposal for TTS, music, SFX, lip sync or transcription. This route only proposes; human approval and execution use the standard proposal routes.", '{"task": "tts|music|sfx|lipsync|transcribe", "target": "s01", "options": {}}', "proposal object"),
    ("POST", "/api/projects/{name}/voiceover/plan", False, "Assets and shots", "Plan a voiceover batch with one TTS proposal per voiced on-camera or off-camera shot. Human session only; the batch awaits approval.", '{"voice": {"voice_id": "...", "cloned": false}}', "awaiting-approval batch"),
    ("POST", "/api/projects/{name}/clips/{shot_id}/extend", True, "Assets and shots", "Create a proposal to extend an existing video clip; nothing is spent until a human approves it.", '{"prompt": "...", "seconds": 5}', 'proposal object'),
    # ---- budget, proposals, approvals
    ("POST", "/api/projects/{name}/estimate", True, "Budget, proposals and approvals", "Compute the budget estimate and stop-loss (free). A human must approve it before anything runs.", '{"failure": 0.2}', "budget object"),
    ("POST", "/api/projects/{name}/budget/approve", False, "Budget, proposals and approvals", "Approve the current estimate (a human decision).", "-", "budget object"),
    ("POST", "/api/projects/{name}/proposals", True, "Budget, proposals and approvals", "Propose ONE paid action (kind image | clip | image_edit | clip_extend | review, target = image or shot id). Nothing is spent. For an API key the approval code is NOT returned.", '{"kind": "image", "target": "s01"}', '{"id", "price", "model", "status", "code"}'),
    ("POST", "/api/projects/{name}/proposals/{pid}/approve", False, "Budget, proposals and approvals", "Approve a proposal with its one-time code (the page does this).", '{"code": "123456"}', "proposal"),
    ("POST", "/api/projects/{name}/proposals/{pid}/approve-human", False, "Budget, proposals and approvals", "Approve a proposal as the human at the terminal or page.", "-", "proposal"),
    ("POST", "/api/projects/{name}/proposals/{pid}/reject", False, "Budget, proposals and approvals", "Reject a proposal.", "-", '{"ok": true}'),
    ("GET", "/api/projects/{name}/generate-all", False, "Budget, proposals and approvals", "The exact price of everything still to generate (images then clips). Creates nothing, spends nothing. The page uses it for Generate all.", "-", '{"items": [{kind, target, label, price, model}], "total", "budget"}'),
    ("POST", "/api/projects/{name}/batches", True, "Budget, proposals and approvals", "Freeze the Generate-all plan as a batch: every item with its model, price and request hash, plus the total and a batch_hash. Creates a file only; nothing is approved or spent.", "-", '{"id", "items", "total", "batch_hash", "status": "awaiting_approval"}'),
    ("GET", "/api/projects/{name}/batches", True, "Budget, proposals and approvals", "List the project's batches.", "-", '{"batches": [{id, status, total, items}]}'),
    ("GET", "/api/projects/{name}/batches/{bid}", True, "Budget, proposals and approvals", "One batch with the status of each item (pending, running, done, needs_reapproval, error).", "-", "batch object"),
    ("POST", "/api/projects/{name}/batches/{bid}/approve", False, "Budget, proposals and approvals", "Approve the batch (a human decision, bound to its batch_hash and exact total).", '{"batch_hash": "..."}', "batch object"),
    ("POST", "/api/projects/{name}/crew/runs", False, "Generation jobs", "Start a studio-crew agent on a task (human session only for now; API keys cannot start runs). autonomy = assist (changes are only suggested as diffs) or copilot (free changes applied and undoable; paid work only as proposals plus one batch a human must approve). The run is a ledger job; the agent can never approve, run, spend or override.", '{"agent": "<id>", "task": "...", "autonomy"?: "assist|copilot"}', '{"job": "<id>", "run": "<id>"}'),
    ("GET", "/api/projects/{name}/crew/runs", True, "Generation jobs", "List the project's crew runs.", "-", '{"runs": [{id, agent, task, autonomy, status, steps, llm_usd}]}'),
    ("GET", "/api/projects/{name}/crew/runs/{rid}", True, "Generation jobs", "One crew run: step log (tool, args, result, tokens, cost), document diffs, suggested changes, proposals and the batch awaiting approval.", "-", "run record"),
    ("POST", "/api/projects/{name}/crew/runs/{rid}/undo", False, "Generation jobs", "Undo a finished run: every document it changed is restored to its pre-run version (as a new history version). Human session only.", "-", '{"ok", "restored": [...]}'),
    ("GET", "/api/projects/{name}/crew/plan", False, "Generation jobs", "The run plan for a stage run or 'make_video' (?stages=a,b or make_video, ?autonomy=, ?checkpoints={json}): agents, missing prerequisites, estimated paid items at today's exact prices per stage, checkpoints, the LLM usage cap and a plan_hash. Creates nothing, spends nothing. Human session only.", "-", "plan"),
    ("POST", "/api/projects/{name}/crew/plan", False, "Generation jobs", "Same as GET, with the options in the body. Human session only.", '{"stages": ["qa"] | "make_video", "autonomy"?: "assist|copilot", "checkpoints"?: {"qa": true}}', "plan"),
    ("POST", "/api/projects/{name}/crew/stages/{stage}/run", False, "Generation jobs", "Start a stage (write_storyboard, cast_and_design, create_scenes, generate_images, generate_clips, assemble_edit, qa) or make_video. Needs the plan_hash of the plan the human reviewed; refuses when prerequisites are missing. A stage ends at a checkpoint (awaiting_checkpoint) with a card. Paid work only becomes proposals and a batch a human approves. Human session only.", '{"plan_hash": "...", "autonomy"?: "assist|copilot", "checkpoints"?: {"stage": true}}', '{"job", "run", "plan"}'),
    ("POST", "/api/projects/{name}/crew/runs/{rid}/continue", False, "Generation jobs", "A human's decision on a stage run waiting at a checkpoint or blocked: approve_continue, edit_continue (after editing the files) or stop. Recorded in the run record. Human session only.", '{"decision": "approve_continue|edit_continue|stop", "note"?: "..."}', '{"job", "run"} (stop returns the run)'),
    ("GET", "/api/crew/agents", False, "Providers, models and limits", "The studio crew's agents: role, tools (fixed), effective prompt and limits, which parts are overridden, and the hard limits. Human session only.", "-", '{"agents": [...], "hard_limits": {...}}'),
    ("PUT", "/api/crew/agents/{agent_id}", False, "Providers, models and limits", "Override one agent's prompt and/or limits (settings/agents.json). Tools can never be changed and limits above the hard caps are refused; {} resets. Human session only.", '{"prompt"?: "...", "limits"?: {"max_steps": 10, "max_tokens": 20000, "max_llm_usd": 0.25}}', "the effective agent"),
    ("POST", "/api/projects/{name}/crew/runs/{rid}/stop", False, "Generation jobs", "Ask a running crew run to stop after its current step. Human session only.", "-", "the job row"),
    ("POST", "/api/projects/{name}/batches/{bid}/run", False, "Generation jobs", "Run an approved batch on the server, one item at a time. Each item is re-checked (model, price, request) first; a change stops that item as needs_reapproval. Returns a job id; poll the batch for progress.", "-", '{"job": "<id>"}'),
    # ---- generation jobs
    ("POST", "/api/projects/{name}/proposals/{pid}/execute", True, "Generation jobs", "Run a proposal a human ALREADY approved (spends money in real projects). Fails if not approved, changed, expired or over budget. Returns a job id.", '{"override": false}', '{"job": "<id>"}'),
    ("GET", "/api/jobs", True, "Generation jobs", "The durable job ledger (survives a server restart). ?project= and ?state= filter it.", "-", '{"jobs": [{id, project, kind, target, state, progress, error, provider_job, batch_id, actor, created, updated}]}'),
    ("GET", "/api/jobs/{jid}", True, "Generation jobs", "Poll a job: running (with progress for exports), done (result; also while the provider is still rendering) or error (failed, cancelled or needs_sync after a restart). state has the exact ledger state.", "-", '{"status": "running|done|error", "state", "result"?, "error"?, "progress"?}'),
    ("POST", "/api/jobs/{jid}/cancel", False, "Generation jobs", "Cancel a job. Queued: stops at once. Running or waiting on a provider: asks it to stop, and the provider may still bill. Human session only.", "-", "the job row"),
    ("POST", "/api/projects/{name}/sync", False, "Generation jobs", "Resolve timed-out or interrupted jobs (fetches the real cost and clip if they finished).", "-", "sync report"),
    # ---- review and export
    ("GET", "/api/projects/{name}/edit", True, "Review and Export", "The editor's edit list (timeline: video, text, audio), what is missing, ffmpeg availability and past exports.", "-", '{"edit", "saved", "missing", "tools", "exports"}'),
    ("PUT", "/api/projects/{name}/edit", False, "Review and Export", "Save the edit list (validated: paths, ranges, fonts, transitions).", "edit object", '{"edit"}'),
    ("POST", "/api/projects/{name}/edit/export", False, "Review and Export", "Render the edit to an MP4 with ffmpeg (free). Returns a job id; poll /api/jobs/{id} for progress.", "-", '{"job"}'),
    ("GET", "/api/projects/{name}/edit/export-fcpxml", False, "Review and Export", "The timeline as Final Cut Pro XML (fcpxml) with the cut points, the dissolves and the music: imports into Final Cut Pro, DaVinci Resolve and other NLEs. Free.", "-", "fcpxml text"),
    ("GET", "/api/projects/{name}/edit/export-edl", False, "Review and Export", "The timeline as a CMX 3600 EDL (Premiere, DaVinci Resolve, Avid, Lightworks): picture and audio events with source and record timecodes. Free.", "-", "EDL text"),
    ("GET", "/api/projects/{name}/edit/export-subtitles", False, "Review and Export", "The subtitle cues as SubRip or WebVTT for Canva, YouTube, TikTok and Google Vids. ?format=srt|vtt (default srt). Free.", "-", "caption file"),
    ("GET", "/api/projects/{name}/edit/export-bundle", False, "Review and Export", "The Canva / Google Vids zip: the media the timeline uses, captions.srt and captions.vtt, timeline.fcpxml, timeline.edl, timeline_summary.json and the newest rendered preview. Free.", "-", "application/zip"),
    ("GET", "/api/projects/{name}/edit/export/{fmt}", False, "Review and Export", "Download an interchange export: otio, otioz, xmeml, fcpxml, edl, srt, vtt or bundle.", "-", "file download"),
    ("GET", "/api/projects/{name}/export/{fmt}", False, "Review and Export", "Download an interchange export: otio, otioz, xmeml, fcpxml, edl, srt, vtt, bundle or aftereffects.jsx. Human session or paired device token only.", "-", "file download"),
    ("GET", "/api/projects/{name}/export/aftereffects.jsx", False, "Review and Export", "Generate an After Effects ExtendScript (.jsx) comp script that imports media and lays out the timeline. Project-contained. Human session or paired device token only.", "-", "ExtendScript (.jsx) file"),
    ("GET", "/api/projects/{name}/media", False, "Review and Export", "Approved stills, clips and audio for editing panels with sizes, sha and download paths. Human session or paired device token only.", "query parameters (?approved=1)", '{"media": [...]}'),
    ("POST", "/api/projects/{name}/edit/import-otio", False, "Review and Export", "Preview an OTIO round trip. Apply by reviewing the diff and saving with PUT /edit.", '{"otio": "..."}', "diff preview"),
    ("POST", "/api/projects/{name}/external-edit", False, "Review and Export", "Open a project media copy in a desktop application. Human session only.", '{"file": "clips/a.mp4", "app"?: "..."}', "session"),
    ("GET", "/api/projects/{name}/external-edit", False, "Review and Export", "List active external edit sessions. Human session only.", "-", "sessions"),
    ("POST", "/api/projects/{name}/external-edit/stop", False, "Review and Export", "Stop an external edit session. Human session only.", "-", "stopped"),
    ("GET", "/api/external-apps", False, "Settings", "List approved desktop application names.", "-", "apps"),
    ("PUT", "/api/external-apps", False, "Settings", "Set approved desktop application names.", '{"apps": ["..."]}', "apps"),
    ("GET", "/api/projects/{name}/comments", True, "Review and Export", "List comments on the edit, shots or assets. ?target= and ?status= filter.", "-", '{"comments": [{id, target, time, author, text, status, created}]}'),
    ("GET", "/api/projects/{name}/history", False, "Review and Export", "List saved versions of one tracked project document, newest first. Human session only; versions can contain prompts.", "?doc=Story.md|shots.json|images.json|edit.json|brief.json|todos.json|comments.json", '{"entries": [{"ts", "size", "sha"}]}'),
    ("GET", "/api/projects/{name}/history/{doc}/{ts}", False, "Review and Export", "Read one saved document version. JSON documents return JSON; Story.md returns {text}. Human session only.", "-", "document version"),
    ("GET", "/api/projects/{name}/history/{doc}/{ts}/diff", False, "Review and Export", "Summarize added, removed and changed top-level keys versus the current JSON document. Human session only.", "-", '{"added": [], "removed": [], "changed": []}'),
    ("POST", "/api/projects/{name}/history/{doc}/{ts}/restore", False, "Review and Export", "Restore a saved document as a new history-aware save; previous versions remain available. Human session only.", "-", '{"version": ..., "entries": [...]}'),
    ("POST", "/api/projects/{name}/comments", False, "Review and Export", "Add a comment on the edit, a shot or an asset. Human session only.", '{"target": "edit|shot:s01|asset:hero", "text": "...", "author": "...", "time"?: 12.4}', "comment object"),
    ("PATCH", "/api/projects/{name}/comments", False, "Review and Export", "Resolve or reopen a comment. Human session only.", '{"id": "...", "action": "resolve|reopen"}', "comment object"),
    ("DELETE", "/api/projects/{name}/comments", False, "Review and Export", "Delete a comment. Human session only.", '{"id": "..."}', '{"id", "deleted": true}'),
    ("POST", "/api/projects/{name}/review-package", False, "Review and Export", "Export a self-contained offline review package as a zip archive (video, shot list, poster frames, open comments). Human session only.", '{"include_prompts"?: false}', "application/zip"),
    ("POST", "/api/projects/{name}/comments/import-feedback", False, "Review and Export", "Import reviewer feedback (feedback.json) and merge comments into the project. Human session only.", "feedback.json contents (up to 1 MB)", '{"imported", "total", "comments"}'),
    ("GET", "/api/projects/{name}/captions/preview", True, "Review and Export", "The caption cues of one shot: the shot's voice line (or the english gloss), timed over the shot. Read-only: nothing is written and no provider is called. ?shot=s01&duration=4&max_chars=42&max_lines=2. Free.", "query parameters", '{"shot", "script", "source", "duration", "cues": [{"text", "start", "end"}]}'),
    ("GET", "/api/projects/{name}/exports", True, "Review and Export", "Rendered MP4s in the project's exports folder.", "-", '{"exports": [{file, bytes, when}]}'),
    ("GET", "/api/delivery/presets", True, "Review and Export", "List validated local delivery presets.", "-", '{"presets": [...]}'),
    ("GET", "/api/projects/{name}/publish", False, "Review and Export", "Read publishing metadata. Human session only.", "-", "publish metadata"),
    ("PUT", "/api/projects/{name}/publish", False, "Review and Export", "Validate and save publishing metadata with history. Human session only.", "publish metadata", "publish metadata"),
    ("POST", "/api/projects/{name}/publish/draft", False, "Review and Export", "Draft metadata with the project's chat role. Human session only.", '{"platform": "youtube"}', "draft metadata"),
    ("POST", "/api/projects/{name}/publish/export", False, "Review and Export", "Render and package a local export for a delivery preset. No upload or posting occurs.", '{"preset": "youtube"}', "export result and preflight findings"),
    ("POST", "/api/projects/{name}/publish/thumbnail", False, "Review and Export", "Choose a frame from project media as the local publishing thumbnail. Human session only.", '{"source": "clips/shot.mp4", "time": 2.5}', '{"thumbnail": "exports/thumbnails/<id>.png"}'),
    ("POST", "/api/projects/{name}/audio", False, "Review and Export", "Upload music or a sound (mp3, wav, m4a, aac, ogg) to the project's audio folder. ?filename=song.mp3", "raw audio bytes (up to 25 MB)", '{"src", "name", "duration"}'),
    ("GET", "/api/projects/{name}/elements", True, "Review and Export", "Images the timeline can overlay: the uploaded elements plus the project stills.", "-", '{"elements": [{src, name, kind}]}'),
    ("POST", "/api/projects/{name}/elements", False, "Review and Export", "Upload an image to elements/<slug>.<ext> (never overwrites: a number is added). ?filename=sticker.png", "raw image bytes (up to 25 MB)", '{"src", "name"}'),
    ("GET", "/api/fonts", False, "Review and Export", "Fonts and weights the text editor can use. Public (no token): the page loads them with CSS.", "-", '{"fonts": [...]}'),
    ("GET", "/api/fonts/{file}", False, "Review and Export", "One bundled font file (whitelisted names only). Public.", "-", "font/ttf"),
    # ---- costs and verification
    ("GET", "/api/projects/{name}/spec/{kind}/{target}", True, "Costs and verification", "Read-only preview of what one generation will be: model, snapped seconds, resolution, frames, references, the model's capability profile, price and warnings. kind = image | clip | image_edit | clip_extend. Estimates, proposals and execution use this same spec.", "-", "spec object"),
    ("GET", "/api/projects/{name}/costs", True, "Costs and verification", "Cost log, used versus discarded spend, and the budget.", "-", "costs object"),
    ("GET", "/api/projects/{name}/usage", False, "Costs and verification", "AI usage (chat, verify, vision) by model: calls and cost.", "-", '{"rows": [...]}'),
    ("GET", "/api/projects/{name}/verify", True, "Costs and verification", "Verification of brief, story, assets, shots and todos: rule findings (always fresh) plus the latest AI review.", "-", "verification status"),
    ("POST", "/api/projects/{name}/verify", False, "Costs and verification", "Run the AI review now for a scope (uses your verify model).", '{"scope": "shots"}', '{"running": true}'),
    # ---- providers, models, limits
    ("GET", "/api/setup", True, "Providers, models and limits", "First-run status: is a provider connected and a chat model chosen; which of chat, image, video are ready.", "-", '{"needed", "providers", "roles"}'),
    ("GET", "/api/provider-types", False, "Providers, models and limits", "Provider kinds you can add (OpenRouter, Google, OpenAI, Anthropic, Runway, Kling, Replicate, custom).", "-", '{"types": [...]}'),
    ("GET", "/api/providers", True, "Providers, models and limits", "Connected providers with status. Keys are never returned, only whether one is set and its last 4 characters.", "-", '{"providers": [...]}'),
    ("POST", "/api/providers", False, "Providers, models and limits", "Add a provider. The session token must be sent in the x-aistudio-token header (never in a URL).", '{"type": "openrouter", "label": "...", "secret": {"api_key": "..."}}', "provider"),
    ("PATCH", "/api/providers/{pid}", False, "Providers, models and limits", "Rename, change base URL, enable or disable.", '{"label"?, "base_url"?, "enabled"?}', "provider"),
    ("DELETE", "/api/providers/{pid}", False, "Providers, models and limits", "Remove a provider (and its key). ?force=1 also removes it from model chains.", "-", '{"ok", "removed_from"}'),
    ("GET", "/api/providers/chatgpt/oauth/status", False, "Providers, models and limits", "ChatGPT subscription sign-in status: is a Codex CLI session detected, is ChatGPT connected (never returns tokens).", "-", '{"codex_detected", "connected", "plan"}'),
    ("POST", "/api/providers/chatgpt/oauth/import-codex", False, "Providers, models and limits", "Connect ChatGPT by importing the signed-in Codex CLI session (~/.codex/auth.json). Header-only token.", "-", "provider"),
    ("GET", "/api/providers/chatgpt/oauth/port-check", False, "Providers, models and limits", "Check if port 1455 is free to receive the ChatGPT OAuth callback.", "-", '{"free", "port"}'),
    ("GET", "/api/providers/chatgpt/oauth/authorize", False, "Providers, models and limits", "Start the browser sign-in with ChatGPT; open the returned url.", "-", '{"url", "state"}'),
    ("GET", "/api/providers/chatgpt/oauth/callback", False, "Providers, models and limits", "OAuth redirect target: exchanges the code (checked against the pending state) and saves the session.", "-", "HTML page"),
    ("PUT", "/api/providers/{pid}/secret", False, "Providers, models and limits", "Save or replace a provider's key (header-only token). Write-only: it can never be read back.", '{"api_key": "..."}', "provider"),
    ("DELETE", "/api/providers/{pid}/secret", False, "Providers, models and limits", "Delete a provider's saved key.", "-", "provider"),
    ("POST", "/api/providers/{pid}/test", False, "Providers, models and limits", "Check that the key and connection work.", "-", '{"result": {ok, message}}'),
    ("GET", "/api/providers/{pid}/models", False, "Providers, models and limits", "Models a provider offers (live list or your own entries). ?refresh=1 re-reads.", "-", '{"models", "error"}'),
    ("POST", "/api/providers/{pid}/models", False, "Providers, models and limits", "Add a model by id when it is not listed.", '{"id": "vendor/model", "capability": "chat|vision|image|video"}', '{"models"}'),
    # ---- ComfyUI workflows (plan 25)
    ("GET", "/api/comfy/workflows", False, "ComfyUI workflows", "List registered ComfyUI workflow templates (human session only).", "-", '{"workflows": [{id, task, inputs, profile}]}'),
    ("GET", "/api/comfy/workflows/{wf_id}", False, "ComfyUI workflows", "Get one workflow template with its full manifest and workflow JSON (human session only).", "-", 'workflow object (id, task, inputs, profile, workflow)'),
    ("POST", "/api/comfy/workflows", False, "ComfyUI workflows", "Register a new ComfyUI workflow template from API JSON and manifest. Validates the mapping. Human session only.", '{"workflow": {...}, "manifest": {...}}', 'workflow object (id, task, inputs, profile)'),
    ("POST", "/api/comfy/workflows/validate", False, "ComfyUI workflows", "Dry-run validation of a workflow and manifest without saving. Human session only.", '{"workflow": {...}, "manifest": {...}}', '{"ok": true, "id", "task", "inputs", "profile"}'),
    ("DELETE", "/api/comfy/workflows/{wf_id}", False, "ComfyUI workflows", "Delete (move to trash) a registered workflow template. Human session only.", "-", '{"deleted": "id", "trash": "path"}'),
    ("GET", "/api/models", False, "Providers, models and limits", "Every known model across providers. ?capability= filters.", "-", '{"models", "errors"}'),
    ("GET", "/api/capabilities", False, "Providers, models and limits", "Every image and video model with its effective capability profile, your override and its price. Human session only.", "?capability=video|image", '{"models": [{provider, id, profile, override, price, ...}]}'),
    ("PUT", "/api/capabilities/{pid}/{model}", False, "Providers, models and limits", "Save your override of a model's capability profile (settings/models.json 'capabilities'); validated against the profile schema. Human session only.", "partial profile", '{"profile", "override"}'),
    ("DELETE", "/api/capabilities/{pid}/{model}", False, "Providers, models and limits", "Remove your capability override. Human session only.", "-", '{"ok": true}'),
    ("PUT", "/api/prices/{pid}/{model}", False, "Providers, models and limits", "Set a price card for a model (per image or per second).", "price card", '{"price", "card"}'),
    ("DELETE", "/api/prices/{pid}/{model}", False, "Providers, models and limits", "Remove your price override.", "-", '{"ok": true}'),
    ("GET", "/api/roles", True, "Providers, models and limits", "The model chain for each role (chat, verify, vision, image, video), in fallback order, plus limits.", "-", '{"roles", "allow_paid", "ai_cap_usd", "auto_verify"}'),
    ("PUT", "/api/roles/{role}", False, "Providers, models and limits", "Set a role's ordered chain of models.", '{"chain": [{"provider", "model"}], "policy"?}', "roles object"),
    ("POST", "/api/roles/reset", False, "Providers, models and limits", "Reset the chains to the defaults.", "-", "roles object"),
    ("POST", "/api/roles/{role}/test", False, "Providers, models and limits", "Check every model of a chain.", "-", '{"role", "results"}'),
    ("PUT", "/api/limits", False, "Providers, models and limits", "Allow paid text models, set the per-project AI spending cap, turn auto-verify on or off.", '{"allow_paid"?, "ai_cap_usd"?, "auto_verify"?}', "roles object"),
    ("GET", "/api/ai", False, "Providers, models and limits", "Older combined view of the chat and verify model lists and limits.", "-", '{"settings", "stored", "locked"}'),
    ("PUT", "/api/ai", False, "Providers, models and limits", "Older way to save the chat and verify model lists and limits.", "settings object", '{"settings"}'),
    ("GET", "/api/ai/models", False, "Providers, models and limits", "Chat model catalog with prices (live from OpenRouter, or the built-in list offline).", "-", '{"models", "source"}'),
    # ---- integrations
    ("GET", "/api/keys", False, "Integrations", "List API keys: name, first characters, created, last used. Never the key.", "-", '{"keys": [...]}'),
    ("POST", "/api/keys", False, "Integrations", "Create an API key. The key is returned once and cannot be shown again. Header-only token.", '{"name": "my-script"}', '{"key": "aisk_...", "record"}'),
    ("DELETE", "/api/keys/{kid}", False, "Integrations", "Revoke an API key at once.", "-", '{"ok": true}'),
    ("POST", "/api/pair/start", False, "Integrations", "Start 6-digit device pairing for NLE panels. Code shown in human notifications and terminal, never in the API. Human session only.", "-", '{"id", "expires", "message"}'),
    ("POST", "/api/pair/confirm", False, "Integrations", "Confirm 6-digit pairing code and receive a scoped device token (returned once). Public endpoint.", '{"code": "123456", "host": "premiere|resolve|aftereffects|blender", "device_name": "..."}', '{"device_token": "aisd_...", "device": {...}}'),
    ("GET", "/api/pair/devices", False, "Integrations", "List paired NLE devices. Human session only.", "-", '{"devices": [{id, host, device_name, created, expires, last_used}]}'),
    ("DELETE", "/api/pair/devices/{id}", False, "Integrations", "Revoke a paired NLE device. Human session only.", "-", '{"ok": true, "revoked": "id"}'),
    ("GET", "/api/integrations", False, "Integrations", "The MCP connection details of this install (python path, repo, workspace) and the MCP tool list.", "-", '{"mcp", "tools", "base_url"}'),
    ("GET", "/api/agents", False, "Integrations", "List detected terminal AI agents (Claude Code, Antigravity CLI, OpenCode).", "-", '{"agents": [{id, name, binary, detected, description}]}'),
    ("POST", "/api/agents/run", False, "Integrations", "Execute a task with a detected terminal AI agent and stream SSE output.", '{"agent_id": "claude", "prompt": "...", "project": "..."}', "text/event-stream"),
    ("POST", "/api/agents/abort", False, "Integrations", "Abort a running terminal AI agent process.", '{"agent_id": "claude"}', '{"ok": true}'),
    ("GET", "/api/docs/endpoints", True, "Integrations", "This reference as data: every route with its group, summary, body, result and whether an API key may call it.", "-", '{"endpoints": [...], "groups": [...]}'),
    # ---- files and utility
    ("GET", "/api/health", True, "Files and utility", "Is the server up? Public (no token).", "-", '{"ok": true}'),
    ("GET", "/files/{name}/{path}", True, "Files and utility", "Read a file of a project: stills, clips, checks, audio, exports (png, jpg, mp4, json, md, csv, txt, mp3, wav, m4a, aac, ogg). Supports ?token=.", "-", "the file"),
]

DEVICE_ALLOWED_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/projects"),
    ("GET", "/api/projects/{name}"),
    ("GET", "/api/projects/{name}/media"),
    ("GET", "/api/projects/{name}/export/{fmt}"),
    ("GET", "/api/projects/{name}/export/aftereffects.jsx"),
    ("GET", "/api/projects/{name}/edit/export/{fmt}"),
    ("GET", "/files/{name}/{path}"),
    ("GET", "/api/jobs"),
    ("GET", "/api/jobs/{jid}"),
    ("POST", "/api/projects/{name}/proposals"),
    ("POST", "/api/projects/{name}/clips/{shot_id}/tool"),
    ("POST", "/api/projects/{name}/clips/{shot_id}/extend"),
    ("POST", "/api/projects/{name}/shots/{shot}/camera-move"),
}

DOCS = {f"{m} {p}": {"method": m, "path": p, "agent": a, "device": (m, p) in DEVICE_ALLOWED_ROUTES, "group": g, "summary": s, "body": b, "returns": r} for m, p, a, g, s, b, r in R}


def endpoints():
    order = {g: i for i, g in enumerate(GROUPS)}
    return sorted(DOCS.values(), key=lambda d: (order.get(d["group"], 99), d["path"], d["method"]))


def undocumented(app):
    """Routes of the app that are missing from DOCS (a test keeps this empty)."""
    missing = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not (path.startswith("/api") or path.startswith("/files")):
            continue
        for m in getattr(r, "methods", None) or []:
            if m in ("HEAD", "OPTIONS"):
                continue
            key = f"{m} {path.replace(':path', '')}"
            if key not in DOCS:
                missing.append(key)
    return missing


def agent_allowed(method, route_path):
    d = DOCS.get(f"{method} {(route_path or '').replace(':path', '')}")
    return bool(d and d["agent"])


def device_allowed(method, route_path):
    clean_path = (route_path or "").replace(":path", "")
    if (method, clean_path) in DEVICE_ALLOWED_ROUTES:
        return True
    d = DOCS.get(f"{method} {clean_path}")
    return bool(d and d.get("device"))
