"""The single description of every HTTP route: used by the Help page (API reference), by the key scope check (agent=True means an API key may call it)
and by a test that fails when a route is added without being described here.

Fields: (method, path, agent, group, summary, body, returns).  agent=True: allowed for API keys (same power as the MCP tools).  False: needs the
page's session token (a human): approvals, budget, providers, keys, limits, deleting.
"""
GROUPS = ["Projects", "Story and documents", "Chat (producer)", "Assets and shots", "Budget, proposals and approvals", "Generation jobs", "Review and Export",
          "Costs and verification", "Library", "Providers, models and limits", "Integrations", "Files and utility"]

R = [
    ("GET", "/api/library", True, "Library", "Search the workspace generation library. Read-only; results can span projects.", "query parameters", '{"items": [...], "total"}'),
    ("GET", "/api/library/{id}", True, "Library", "Read one library item.", "-", "library item"),
    ("POST", "/api/library/{id}/favorite", False, "Library", "Mark or unmark a library item as favorite. Human session only.", '{"on": true}', "library item"),
    ("POST", "/api/library/rebuild", False, "Library", "Rebuild the index from project media and cost logs. Human session only.", "-", '{"count": 0}'),
    ("POST", "/api/library/promote", False, "Library", "Copy a project asset into the workspace library. Human session only.", '{"project": "...", "file": "stills/hero.png"}', "library item"),
    ("POST", "/api/library/use", False, "Library", "Copy a workspace library asset into a project. Human session only.", '{"id": "...", "project": "...", "kind": "image"}', "library item"),
    ("POST", "/api/library/remix", False, "Library", "Return a prefilled proposal request; does not create a proposal or spend money. Human session only.", '{"id": "...", "project": "..."}', "proposal request"),
    # ---- projects
    ("GET", "/api/projects", True, "Projects", "List projects.", "-", '{"projects": [{name, shots, assets, spent, estimate, approved, test, favorite}]}'),
    ("POST", "/api/projects", True, "Projects", "Create a project from the guided templates.", '{"name": "my-ad", "test_pipeline": false}', '{"name": "my-ad"}'),
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
    ("POST", "/api/projects/{name}/character/analyze", True, "Assets and shots", "Create a proposal for paid character-image analysis; nothing is spent until a human approves the proposal.", '{"rel": "stills/gandhi.png"}', 'proposal object'),
    ("GET", "/api/projects/{name}/stills/unregistered", False, "Assets and shots", "Images in stills/ that are not in the asset list yet, with a category guess.", "-", '{"files": [...]}'),
    ("POST", "/api/projects/{name}/stills/import", False, "Assets and shots", "Register existing images as assets (renames files to <id>.<ext>).", '{"items": [{"file", "id", "kind"}]}', "overview object"),
    ("POST", "/api/projects/{name}/assets/{aid}/rename", True, "Assets and shots", "Rename an asset id everywhere (files, references, shots, cost log).", '{"new": "..."}', "overview object"),
    ("POST", "/api/projects/{name}/shots/{sid}/rename", True, "Assets and shots", "Rename a shot id everywhere (clips, cost log, discarded history).", '{"new": "..."}', "overview object"),
    ("POST", "/api/projects/{name}/shots/{shot}/approve", False, "Assets and shots", "Approve the newest completed clip of a shot (a human decision).", "-", "shot"),
    ("POST", "/api/projects/{name}/discard", True, "Assets and shots", "Move a clip or still to _discarded with a reason (never deletes).", '{"rel": "clips/s01_final_a1.mp4", "reason": "..."}', "discard record"),
    ("POST", "/api/projects/{name}/restore", True, "Assets and shots", "Restore a discarded file.", '{"rel": "clips/_discarded/..."}', '{"file"}'),
    ("POST", "/api/projects/{name}/stills/{shot_id}/edit", True, "Assets and shots", "Create a proposal for an inpaint, outpaint or background-swap edit; nothing is spent until a human approves it.", '{"prompt": "...", "edit_mode": "inpaint_insertion", "mask_mode": "MASK_MODE_BACKGROUND"}', 'proposal object'),
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
    ("GET", "/api/projects/{name}/exports", True, "Review and Export", "Rendered MP4s in the project's exports folder.", "-", '{"exports": [{file, bytes, when}]}'),
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
    ("GET", "/api/models", False, "Providers, models and limits", "Every known model across providers. ?capability= filters.", "-", '{"models", "errors"}'),
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
    ("GET", "/api/integrations", False, "Integrations", "The MCP connection details of this install (python path, repo, workspace) and the MCP tool list.", "-", '{"mcp", "tools", "base_url"}'),
    ("GET", "/api/agents", False, "Integrations", "List detected terminal AI agents (Claude Code, Antigravity CLI, OpenCode).", "-", '{"agents": [{id, name, binary, detected, description}]}'),
    ("POST", "/api/agents/run", False, "Integrations", "Execute a task with a detected terminal AI agent and stream SSE output.", '{"agent_id": "claude", "prompt": "...", "project": "..."}', "text/event-stream"),
    ("POST", "/api/agents/abort", False, "Integrations", "Abort a running terminal AI agent process.", '{"agent_id": "claude"}', '{"ok": true}'),
    ("GET", "/api/docs/endpoints", True, "Integrations", "This reference as data: every route with its group, summary, body, result and whether an API key may call it.", "-", '{"endpoints": [...], "groups": [...]}'),
    # ---- files and utility
    ("GET", "/api/health", True, "Files and utility", "Is the server up? Public (no token).", "-", '{"ok": true}'),
    ("GET", "/files/{name}/{path}", True, "Files and utility", "Read a file of a project: stills, clips, checks, audio, exports (png, jpg, mp4, json, md, csv, txt, mp3, wav, m4a, aac, ogg). Supports ?token=.", "-", "the file"),
]

DOCS = {f"{m} {p}": {"method": m, "path": p, "agent": a, "group": g, "summary": s, "body": b, "returns": r} for m, p, a, g, s, b, r in R}


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
